# Example DC deployment

README coming soon

#Files:
- etc/dhcp/dhcpd.conf: Sample dhcp file used in the Vagrant instance
- var/www/ztp_deploy.sh: Zero touch provisioning script.  Copies license
file, and authorized public key for Ansible.
- Vagrant/Vagrantfile: Vagrant definition to stand up virtual network

#Install Instructions
These steps will walk you through setting up your vagrant simulation environment

1.  [Management VM Setup](#management-vm-setup)
+  [Git Setup for Automation Scripts](#git-setup-for-automation-scripts)
+  [Network Setup](#network-setup)
+  [Turn up the rest of the virtual topology via Vagrant](#turn-up-the-rest-of-the-virtual-topology-via-vagrant)
+  [Validate connectivity](#validate-connectivity)
+  [Setup SSH keys and deploy to the network](#setup-ssh-keys-and-deploy-to-the-network)
+  [Provision the Network via Automation](#provision-the-network-via-automation)
+  [Test IPv4 Internet connectivity from server01](#test-ipv4-internet-connectivity-from-server01)
+  [turnup.sh Optional Script](#turnupsh-optional-script)

#Management VM Setup
Clone this git repo to the laptop or server being used to run vagrant
```bash
$ git clone https://github.com/CumulusNetworks/cldemo-vagrant.git
```
Follow the directions in the readme.

- use the vagrant ssh mgmt command to connect to the mgmt vm
```bash
$ vagrant ssh oob-mgmt-server

Welcome to Ubuntu 14.04.4 LTS (GNU/Linux 4.2.0-27-generic x86_64)

 * Documentation:  https://help.ubuntu.com/
----------------------------------------------------------------
  Ubuntu 14.04.4 LTS                          built 2016-02-20
----------------------------------------------------------------
Last login: Mon Mar  7 12:29:28 2016 from 10.0.2.2
vagrant@oob-mgmt-server:~$
```
- On the Management sudo to root
```bash
vagrant@oob-mgmt-server:~$ sudo -i
```
Install the following programs that are needed for automation
```bash
root@oob-mgmt-server:~#
 sudo apt-get update
 sudo apt-get install -y isc-dhcp-server dnsmasq apache2
 sudo apt-get install -y python-pip shedskin libyaml-dev sshpass git
 sudo apt-get install apt-cacher -y
 sudo pip install ansible
 sudo pip install ansible --upgrade
 sudo apt-get install apt-cacher-ng -y
 sudo service apt-cacher restart
```
This completes the mgmt VM setup

##Git Setup for Automation Scripts
Setup your username and email and clone your directory into the mgmt vm
```bash
root@oob-mgmt-server:~#
 git init
 git config --global user.name "Your Name"
 git config --global user.email your_email@domain.com
 git clone https://github.com/CumulusNetworks/unBGPmlag.git
```

##Validate oob connection on the management station
(Make sure the IP is attached to eth0)
```bash
root@oob-mgmt-server:~# ifup eth0
root@oob-mgmt-server:~# ip addr show eth0
```

##Network Setup
Verify network setup is correct and configure DNS, DHCP and WWW directory

###Setup DNS
```bash
root@oob-mgmt-server:~# cat ~/unBGPmlag/etc/hosts | sudo tee /etc/hosts
root@oob-mgmt-server:~# service dnsmasq restart
```

###Setup DHCP
```bash
root@oob-mgmt-server:~# cp ~/unBGPmlag/etc/dhcp/dhcpd.conf /etc/dhcp/dhcpd.conf
root@oob-mgmt-server:~# service isc-dhcp-server restart
```

###Copy WWW Contents  to the Web Directory
```bash
root@oob-mgmt-server:~# cp ~/CUSTOMER/var/www/* /var/www/html/
```

Verify that DHCP is running otherwise VMs will timeout on their DHCP config and slow down their startup process
```bash
vagrant@oob-mgmt-server:~$ /etc/init.d/isc-dhcp-server status
Status of ISC DHCP server: dhcpd is running.
```

#Turn up the rest of the virtual topology via Vagrant:
On your laptop/server in the Vagrant directory perform the following commands:
```bash
$ export VAGRANT_DEFAULT_PROVIDER=virtualbox
$ vagrant up
```

#Validate connectivity
Change into the unBGPmlag directory and run the following commands
```bash
root@oob-mgmt-server:~# cd unBGPmlag
root@oob-mgmt-server:~/unBGPmlag#
root@oob-mgmt-server:~/unBGPmlag# ansible network -m ping -u cumulus -k
  - (pwd: CumulusLinux!)
root@oob-mgmt-server:~/unBGPmlag# ansible servers -m ping -u vagrant -k
  - (pwd: vagrant)
```

#Setup SSH keys and deploy to the network
```bash
root@oob-mgmt-server:~/unBGPmlag# ssh-keygen -t rsa
root@oob-mgmt-server:~/unBGPmlag# cp /root/.ssh/id_rsa.pub /var/www/html/authorized_keys
root@oob-mgmt-server:~/unBGPmlag# cp ~/CUSTOMER/var/www/ztp_deploy.sh /var/www/html/
root@oob-mgmt-server:~/unBGPmlag# ansible-playbook deploy_ssh_keys.yml -u vagrant -k
  - (pwd: vagrant)
```

##Test passwordless connectivity to all (servers will fail, since network is not provisioned yet)
```bash
root@oob-mgmt-server:~/unBGPmlag# ansible -m ping all
```

#Provision the Network via Automation
Make sure to use the --extra-vars statement to run on Vitualbox otherwise it will attempt to run ZTP as it would in production on real equipment.  
```bash
root@oob-mgmt-server:~/unBGPmlag# ansible-playbook unBGPmlag.yml --extra-vars "phys_env=virt"
```

NOTE: WORK AROUND RIGHT NOW, the servers will come up with a vagrant default route for IPv4
this means Ansible does not have reachability, this will require some minor work to the vagrant setup we have
just do this for each server->
```bash
vagrant ssh os-controller-0
```
Then delete default route on the vagrant interface
```bash
root@os-controller-0:~# ip route del default
```
Then add the correct one for its bridge
```bash
root@os-controller-0:~# ip route add default via 10.2.51.1
```

Now Ansible will work

Deploy the keys for the servers (the servers will have received their IPv4 address via the DHCP relay now that the network is up)
```bash
root@mgmt:/home/vagrant/unBGPmlag# ansible-playbook deploy_ssh_keys.yml -k -u vagrant -l servers
```
Deploy config to servers
'''bash
root@mgmt:/home/vagrant/unBGPmlag# ansible-playbook unBGPmlag.yml -l servers
'''

#Test IPv4 Internet connectivity from server01
- vagrant ssh server01
- ping 8.8.8.8

```bash
root@os-controller-0:~# ping6 fd::105 -I 2a06:71c0::1
PING fd::105(fd::105) from 2a06:71c0::1 : 56 data bytes
64 bytes from fd::105: icmp_seq=1 ttl=59 time=2.93 ms
64 bytes from fd::105: icmp_seq=2 ttl=59 time=2.96 ms
64 bytes from fd::105: icmp_seq=3 ttl=59 time=2.95 ms
```

#turnup.sh Optional Script
There is an optional script that will take care of the first 3 steps automatically
```bash
$ vagrant ssh mgmt
Welcome to Ubuntu 14.04.4 LTS (GNU/Linux 4.2.0-27-generic x86_64)

 * Documentation:  https://help.ubuntu.com/
----------------------------------------------------------------
  Ubuntu 14.04.4 LTS                          built 2016-02-20
----------------------------------------------------------------
Last login: Tue Mar  8 17:21:42 2016 from 10.0.2.2
vagrant@mgmt:~$ sudo -i
root@mgmt:~# cd /home/vagrant/
root@mgmt:/home/vagrant# sh turnup.sh
```
