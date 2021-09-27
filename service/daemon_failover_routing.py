#!/usr/bin/env python3

import paho.mqtt.client as mqtt
import base64, json, io, os, subprocess, re, ssl, time, datetime

# ----------------------------------------------------------
#  Prerequisites
# ----------------------------------------------------------
# run "pip3 install paho-mqtt"
# run "apt-get install nmap"
# add "primary" and "secondary" into /etc/iproute2/rt_tables
# run "ip route add table primary 0.0.0.0/0 via x.x.x.x" and fill in your primary gateway ip
# copy over every other route from table main into primary
# run "ip route add table secondary 0.0.0.0/0 via x.x.x.x" and fill in your secondary gateway ip
# copy over every other route from table main into primary
#
# ----------------------------------------------------------
#  SETTINGS
# ----------------------------------------------------------

DEBUG = False

pingInterval = 10                                   # Interval to pause between ping attempts
pingTargetIp = "8.8.8.8"                            # IP used for pinging
ipPrimary = "192.168.0.1"                           # IP of your primary gateway/router
ipSecondary = "192.168.0.2"                         # IP of your secondary gateway/router
macPrimary = "AB:CD:EF:12:34:56"                    # MAC address of your primary gateway/router
macSecondary = "12:34:56:AB:CD:EF"                  # MAC address of your secondary gateway/router
ipPolicyPrimary = "192.168.0.100-192.168.0.149"     # IP range that should alway be routed through your primary gateway/router, if available. You can specify multiple ranges separated by a comma and also input single IPs
ipPolicySecondary = "192.168.0.150-192.168.0.199"   # IP range that should alway be routed through your secondary gateway/router, if available. You can specify multiple ranges separated by a comma and also input single IPs

mqttBaseTopic = "raspberry-gateway"                 # MQTT base topic
mqttClientId = "raspberry-gateway"                  # MQTT client ID
mqttHostname = "192.168.0.3"                        # MQTT server hostname
mqttPort = 1883                                     # MQTT server port (typically 1883 for unencrypted, 8883 for encrypted)
mqttUsername = "yourusername"                       # username for user/pass based authentication
mqttPassword = "youerpassword"                      # password for user/pass based authentication
mqttCA = ""                                         # path to server certificate for certificate-based authentication
mqttCert = ""                                       # path to client certificate for certificate-based authentication
mqttKey = ""                                        # path to client keyfile for certificate-based authentication
mqttConnectionTimeout = 60                          # in seconds; timeout for MQTT connection

# ----------------------------------------------------------
#  DO NOT CHANGE BELOW
# ----------------------------------------------------------

running = True
activePrimary = False
activeSecondary = False

regexLostMatcher = re.compile("Lost:", re.M)
regexLostNoneMatcher = re.compile("Lost: (0|1)", re.M)

# MQTT connect event handler
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connection established.")

        # publish general server info
        client.publish(mqttBaseTopic + "/state", payload="online", qos=1, retain=True)
    else:
        print("Connection could NOT be established. Return-Code:", rc)

# MQTT disconnect event handler
def on_disconnect(client, userdata, rc):
    print("Disconnecting. Return-Code:", str(rc))
    running = False

# MQTT log event handler
def on_log(client, userdata, level, buf):
    print("   [LOG]", buf)

# Get IP Ranges out of a string value
def getIPRanges(value):
    num = 0
    ranges = value.split(',')
    for range in ranges:
        pair = range.split('-')
        rangeStart = pair[0]
        rangeEnd = pair[0]
        if len(pair) > 1:
            rangeEnd = pair[1]
        ips = getIPsFromRange(rangeStart, rangeEnd)
        for ip in ips:
            yield [num, ip]
            num += 1

# Get list of IPs out of an IP Range
def getIPsFromRange(start, end):
    import socket, struct
    start = struct.unpack('>I', socket.inet_aton(start))[0]
    end = struct.unpack('>I', socket.inet_aton(end))[0]
    return [socket.inet_ntoa(struct.pack('>I', i)) for i in range(start, end + 1)]

# Ping primary and secondary
def pingTargets():
    global activePrimary, activeSecondary
    
    # keep previous state
    oldPrimary = activePrimary
    oldSecondary = activeSecondary
    
    # ping primary and secondary
    activePrimary = pingTarget(macPrimary, pingTargetIp)
    activeSecondary = pingTarget(macSecondary, pingTargetIp)
    
    # if any is offline, retry just to make sure
    if activePrimary == False: activePrimary = pingTarget(macPrimary, pingTargetIp)
    if activeSecondary == False: activeSecondary = pingTarget(macSecondary, pingTargetIp)
    
    # revert to old state if ping result was not clear
    if activePrimary == 'Unknown': activePrimary = oldPrimary
    if activeSecondary == 'Unknown': activeSecondary = oldSecondary
    
    # if any state changed, update routing tables
    if oldPrimary != activePrimary or oldSecondary != activeSecondary:
        processStates()

# Ping a single target IP via the specified MAC address
def pingTarget(macAddress, ipTarget):
    p = subprocess.Popen(['sudo', 'nping', '--icmp', '--dest-mac', macAddress, ipTarget], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
    out, err = p.communicate()
    
    pingValid = regexLostMatcher.search(out)
    pingSuccessful = regexLostNoneMatcher.search(out)
    
    if pingValid and pingSuccessful:
        return True
    elif pingValid:
        return False
    else:
        return 'Unknown'

# Clear default gateway multiple times, just to make sure
def clearDefault():
    subprocess.call(['sudo route del default gw ' + ipPrimary], shell=True)
    subprocess.call(['sudo route del default gw ' + ipPrimary], shell=True)
    subprocess.call(['sudo route del default gw ' + ipSecondary], shell=True)
    subprocess.call(['sudo route del default gw ' + ipSecondary], shell=True)

# Clear all policy rules for primary and secondary
def clearPolicy():
    subprocess.call(['while sudo ip rule delete from 0/0 to 0/0 table primary 2>/dev/null; do true; done'], shell=True)
    subprocess.call(['while sudo ip rule delete from 0/0 to 0/0 table secondary 2>/dev/null; do true; done'], shell=True)

# Processes changed states by setting routes for the available WAN
def processStates():
    # Both WAN are active
    if activePrimary and activeSecondary:
        print("all active internet connections")
        subprocess.call(['sudo route del default gw ' + ipSecondary], shell=True)
        subprocess.call(['sudo route add default gw ' + ipPrimary], shell=True)
        
        primaryIps = getIPRanges(ipPolicyPrimary)
        for ip in primaryIps:
            priority = ip[0] + 10000
            subprocess.call(['sudo ip rule add priority ' + str(priority) + ' table primary from ' + ip[1]], shell=True)
            
        secondaryIps = getIPRanges(ipPolicySecondary)
        for ip in secondaryIps:
            priority = ip[0] + 20000
            subprocess.call(['sudo ip rule add priority ' + str(priority) + ' table secondary from ' + ip[1]], shell=True)
        
        client.publish(mqttBaseTopic + "/failover/primary", payload="online", qos=1, retain=True)
        client.publish(mqttBaseTopic + "/failover/secondary", payload="online", qos=1, retain=True)
    
    # Only primary WAN is active
    elif activePrimary:
        print("primary active internet connections")
        subprocess.call(['sudo route del default gw ' + ipSecondary], shell=True)
        subprocess.call(['sudo route add default gw ' + ipPrimary], shell=True)
        clearPolicy()
        
        client.publish(mqttBaseTopic + "/failover/primary", payload="online", qos=1, retain=True)
        client.publish(mqttBaseTopic + "/failover/secondary", payload="offline", qos=1, retain=True)
        
    # Only secondary WAN is active
    elif activeSecondary:
        print("secondary active internet connections")
        subprocess.call(['sudo route del default gw ' + ipPrimary], shell=True)
        subprocess.call(['sudo route add default gw ' + ipSecondary], shell=True)
        clearPolicy()
        
        client.publish(mqttBaseTopic + "/failover/primary", payload="offline", qos=1, retain=True)
        client.publish(mqttBaseTopic + "/failover/secondary", payload="online", qos=1, retain=True)
        
    # No WAN is active - stay calm and carry on
    else:
        print("no active internet connections")


# clear leftover rules from a potential crash
print("clearing previous rules")
clearDefault()
clearPolicy()

# create client instance
client = mqtt.Client(mqttClientId)

# configure authentication
if mqttUsername != "" and mqttPassword != "":
    client.username_pw_set(username=mqttUsername, password=mqttPassword)

if mqttCert != "" and mqttKey != "":
    if mqttCA != "":
        client.tls_set(ca_certs=mqttCA, certfile=mqttCert, keyfile=mqttKey)
    else:
        client.tls_set(certfile=mqttCert, keyfile=mqttKey)
elif mqttCA != "":
    client.tls_set(ca_certs=mqttCA)

# attach event handlers
client.on_connect = on_connect
client.on_disconnect = on_disconnect
if DEBUG is True:
    client.on_log = on_log

# define last will
client.will_set(mqttBaseTopic + "/state", payload="offline", qos=1, retain=True)

# connect to MQTT server
print("Connecting to " + mqttHostname + " on port " + str(mqttPort))
client.connect(mqttHostname, mqttPort, mqttConnectionTimeout)

# start endless loop
client.loop_start()

try:
    while running:
        pingTargets()
        time.sleep(pingInterval)
except KeyboardInterrupt:
    print("Aborting...")

# stop endless loop
client.loop_stop()
