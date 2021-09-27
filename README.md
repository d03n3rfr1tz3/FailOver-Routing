# FailOver-Routing
A simple showcase of a Multi-WAN FailOver including some basic policy routing using just a few linux commands available for example on a Raspberry Pi.

## Network Overview

This showcase explicitly uses the network 192.168.0.X and two gateways (192.168.0.1 and 192.168.0.2), that are not separated. The IP address of the Raspberry Pi will be 192.168.0.3 in this showcase. If your network uses another IP range, change it accordingly. If you have multiple networks (e.g. 192.168.0.X and 192.168.1.X), you have to get enough ethernet ports (or use WiFi) on your Raspberry Pi and bridge them accordingly. I'm not an expert on this topic, so please don't try to get support on anything, especially the bridging part. But I'm sure you'll find some useful tutorials online.

![Network Overview](https://github.com/d03n3rfr1tz3/FailOver-Routing/blob/main/images/network-basic.png)

## Installation / Configuration

Installation is pretty straight forward. You need to install some basic stuff, prepare only a few things and copy over two files. As it might
not be obvious, I will explain every step in detail and give some more insights on how I used it in my home setup. You also can decide and have to make sure, that every step fits your network topology and requirements or otherwise make changes on your own.

### 1. Install NMAP

We need nping from the nmap package. It can ping a target via a gateway without modifying the network configuration or creating virtual ones.
```
sudo apt-get install nmap
```

### 2. Prepare IPv4 Forwarding

The base of all this is to switch your Raspberry Pi into a simple router by activating IPv4 Forwarding. This forwards every unknown/public traffic or traffic that is not targeted to something local. After you have done this, you could start using your Raspberry Pi as a gateway instead of your typical gateway (e.g. your internet router).

To do so, you edit the */etc/sysctl.conf* and make sure the line *net.ipv4.ip_forward=1* is not commented out.
```
sudo nano /etc/sysctl.conf
```
> net.ipv4.ip_forward=1

### 3. Prepare the Routing Tables

#### a) Routing Table Names
You'll have to edit */etc/iproute2/rt_tables* and add two lines. These two lines will represent that names of our routing tables later. In my case I just used 'primary' and 'secondary'.
```
sudo nano /etc/iproute2/rt_tables
```
> 100     primary<br/>
> 101     secondary

#### b) Route via defined Gateway
After you have prepared the names, you need to prepare the concrete routes. Depending on your setup, this can be a bit tricky. The first route we will add into both tables, basically routes every unknown traffic through a defined gateway. Every other route we have to add just makes sure, that other stuff from the 'main' route (e.g. Docker) does not break. Here are the first and important routes.
```
sudo ip route add table primary 0.0.0.0/0 via 192.168.0.1
sudo ip route add table secondary 0.0.0.0/0 via 192.168.0.2
```

#### c) Copy Routes from 'main' table (OPTIONAL)
Beware that this step might be optional, but could be important depending on what your Raspberry Pi does besides routing internet traffic. In my case I installed everything on a Raspberry Pi 4 that is also the Host of my Home Assistant, my DHCP, my DNS (via AdGuard) and my MQTT Broker. The latter ran into some trouble with connection timeouts, because the packets did not get routed accordingly into the Docker instances. Strangly enough only the MQTT Broker had problems, everything else seemed to work. To fix that, I had to copy over about 12 lines from the 'main' table. Most of them were put in place by the Home Assistant Supervisor and/or Docker.

After you have added the first line on each routing table, it is recommended (by me) to copy over every single route from the 'main' table, except the first one. To do so, you have to look into your 'main' table by using the following command.
```
sudo ip route show table main
```
The result of that content could look like the following example, if your Raspberry Pi is fresh and only has basic ethernet. In my case it had a lot more lines. Copy every line, except the first one (because we already got that), into a text editor of your choice.
```diff
- default via 192.168.0.1 dev eth0
  192.168.0.0/24 dev eth0 proto kernel scope link src 192.168.0.3 metric 100
  192.168.0.0/24 dev eth0 proto dhcp scope link src 192.168.0.3 metric 202
```
Now you should have some lines in your editor. Then prepend *sudo ip route add table primary* before every line. Then duplicate each line, but this time replace the word 'primary' with 'secondary' in the duplicated lines. For the example above the outcome should be the following and running them should create each route into both of your prepared tables. Beware that 192.168.0.3 is the IP of the Raspberry Pi.
```
sudo ip route add table primary 192.168.0.0/24 dev eth0 proto kernel scope link src 192.168.0.3 metric 100
sudo ip route add table primary 192.168.0.0/24 dev eth0 proto dhcp scope link src 192.168.0.3 metric 202
sudo ip route add table secondary 192.168.0.0/24 dev eth0 proto kernel scope link src 192.168.0.3 metric 100
sudo ip route add table secondary 192.168.0.0/24 dev eth0 proto dhcp scope link src 192.168.0.3 metric 202
```
NOTE: If you made a mistake filling the Routing Table, you can always clear it with '*sudo ip route flush table primary*' or '*sudo ip route flush table secondary*'

### 4. Put the systemd Service in place

Now that you prepared the Routing Tables and their content, we need to install the systemd service. This service is a Python script and has a very simple task: Periodically ping a target via each gateway and if something is down, it activates/deactivates the routing rules accordingly. It also publishes the state of each WAN into an MQTT Broker. If you don't need that, just remove that part of the script. You can do that! :)

First off, we need to install Python and if you stay with the MQTT functionality also the Python MQTT package. This can be done easily with the following commands.
```
sudo apt-get install python3-pip
sudo pip3 install paho-mqtt
```

Now you basically copy over the Python script to '*/home/pi/scripts/daemon_failover_routing.py*' and the daemon service in a way you prefer. If you are not sure how to do that, I'll give you one of many possibilities.

You can use the following commands to open a text editor (first line) and make the script executable (second line). After running the first line, you simply can copy&paste the content of the [Python script](https://github.com/d03n3rfr1tz3/FailOver-Routing/blob/main/service/daemon_failover_routing.py) from this repository.
```
nano ~/scripts/daemon_failover_routing.py
chmod +x ~/scripts/daemon_failover_routing.py
```
Now you do the same with the systemd service by using the following commands. Again running the first line, you simply can copy&paste the content of the [systemd Service](https://github.com/d03n3rfr1tz3/FailOver-Routing/blob/main/service/failover-routing.service) from this repository.
```
sudo nano /etc/systemd/system/failover-routing.service
sudo systemctl enable failover-routing.service
sudo systemctl start failover-routing.service
```
If everything was done correctly and nothing strange happened in the timeframe between I created this and when you are using it, it already should work. You could change the default gateway of your PC to your new routing Raspberry Pi. But because we are all just humans, I would recommand to at least check the status of the service via using the following command. If it crashes you should look into your *journalctl*, hopefully you'll find the reason and then you just fix it (because this is always easily done /s).
```
sudo systemctl status failover-routing.service
```

### 5. Questions? Celebrate!

You probably have done it, congratulation! But maybe you have a few questions. Here are some I think someone could have and to give some additional insights, that might help or give you some ideas.

#### a) Why 'primary' and not just only 'secondary'?

If you payed close attentation, you might ask yourself, why I did create a Routing Table 'primary' and not just 'secondary', because 'primary' is basically a copy of 'main', while 'secondary' at least has a different gateway.

The thing is, I wanted to build it that way, that I could add some sort of load balancing later. By preparing policy routing for primary and secondary, I can put routes to force traffic through primary and through secondary separately. Then only devices that do not have explicit policy routes would get the default route ('main' table) and at this point, or somewhere inbetween, I can probably add some sort of load balancing later. I'm not sure how, I did not think through that further and I currently do not measure anything that would help implementing a load balancer, but at least the policy routing would already support that.

#### b) Did you do more of that in your home setup?

You might be surprised, but yes. Not only do I use the whole thing in my own network, I implemented it twice. Twice? Yes, I'm serious. You know, sometimes you have to restart a Raspberry Pi or things go downhill just because.

Ok let me start with some basic stuff. I have basically two Raspberry Pis that are mirroring some parts of each other.
* First RPI: DHCP, DNS (AdGuard), Gateway (and some other stuff)
* Second RPI: DNS (AdGuard), Gateway

This means, the DHCP issues leases with two local DNS and two local Gateways. Both (DNS and Gateway) are these two RPIs. If the OS that gets these information is smart enough, it can handle the downtime of one of these RPIs. On top of that, this FailOver Routing is in place for the traffic routed through each RPI into the concrete Internet Router (primary or secondary). Sounds a bit over the top? Yes, maybe... but it replaced a costly Business Router, does work way better and of course also FeelsGoodMan ;)

![Network with Redundancy](https://github.com/d03n3rfr1tz3/FailOver-Routing/blob/main/images/network-redundancy.png)
