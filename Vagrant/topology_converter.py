#
#
#    Topology Converter
#       converts a given topology.dot file to a Vagrantfile
#           can use the virtualbox Vagrant provider
# Initially written by Eric Pulvino 2015-10-19
#
#    Changelog:
#   v1.0 -- 2015-10-19: Initial version constructed
#   v2.0 -- 2016-01-07: Added Support for MAC handout, empty ansible playbook 
#                         (used to generate ansible inventory), [EMPTY] connections 
#                         for more accurate automation simulation, "vagrant" interface
#                         remapping for hosts and switches, warnings for interface 
#                         reuse, added #optional support for OOB switch.
#   v2.1 -- 2016-01-15: Added Support Boot Ordering -- 1st device --> 2nd device --> servers --> switches
#   v2.2 -- 2016-01-19: Added Support for optional switch interface configuration
#   v2.5 -- 2016-01-25: Added LIBVIRT SUPPORT!!! :) and support for fake devices
#   v2.6 -- 2016-01-26: Moved provider and switch/server mem settings from topology_converter to definitions.py
#   v2.7 -- 2016-01-27: Setup cleanup of remap_files added zip file for generated files
#   v2.8 -- 2016-02-05: Added support for .def files along with definitions.py so seperate files can be stored
#                        in the same directory. Also added support for adding topology files to shareable zipfile.
#   v3.0 -- 2016-02-19: Added support for Interface Remapping without reboots on Vx and Hosts (to save time).
#                        Moved any remaining topology-specific settings into the definitions files. So 
#                        topology_converter is truly agnostic and should not need to be modified. Also created
#                        an option to disable the vagrant synced folder to further speed boot. Hardened Interface
#                        remapping on hosts to work on reboots; and not to pause and wait for networking at reboot.
#                        Created remap_eth_swp script that is both hardened and works for both Vx nodes and generic hosts.
#   v3.1 -- 2016-03-03: Added Hidden "use_vagrant_interface" option to optionally use Vagrant interface. Added CLI 
#                        for Debugging mode.
#   v3.2 -- 2016-03-08: Significant changes to surrounding packages i.e. rename_eth_swp script. Minor changes to topology
#                        converter in the way remap files are generated and hosts run the remap at reboot via rc.local
#                        
#
#
version = "3.2"
#
#   to do: 
#       -Use proper dot file parsing library
#       -Add Sanity checking for "good" hostnames (no leading numbers, no spaces, no "_" etc)


import os
import re
import sys
import importlib

from collections import defaultdict

## Hidden Options ##
verbose=False #Debugging Mode
clean_up=True #Removes existing remap_eth Files
use_vagrant_interface=True #Creates and uses Vagrant interface instead of Eth0

#Check Args
if len(sys.argv) < 2 or len(sys.argv) > 3:
    print "\nUsage: $python " + sys.argv[0] + " [Topology File] [-v]"
    print "    examples: $python " + sys.argv[0] + " ./topology.dot"
    print "              $python " + sys.argv[0] + " ./topology.dot -v "
    print "\nOptions:"
    print "   -v : Verbose/Debugging Mode"
    exit(1)

if len(sys.argv) == 3:
    if sys.argv[2] != "-v":
        print " ERROR: Option \"" +  sys.argv[2] + "\" unsupported."
        print "\nOptions:"
        print "   -v : Verbose/Debugging Mode"
        exit(1)
    else:
        verbose=True

#Hardcoded Variables
topology_file=sys.argv[1] #accept our topology file as input
definition_file=topology_file[:-4]+".def"
VAGRANTFILE="./Vagrantfile" #Set our vagrantfile output. Existing VAGRANTFILES will be overwritten
script_storage="./helper_scripts" #Location for our generated remap files
ZIPFILE="./virtual_topology.zip"


#LIBvirt Provider Settings
# start_port and port_gap are only relevant to the libvirt provider. These settings provide the basis
#   for the UDP tunnel construction which is used by libvirt. Since UDB tunnels only make sense in a 
#   point-to-point fashion, there is additional error checking when using the libvirt provider to make
#   sure that interfaces are not reused for a point-to-multipoint configuration.
start_port=8000
port_gap=1000 #make sure you have fewer links than you've specified for the port-gap

#Static Variables -- #Do not change!
warning=False
libvirt_reuse_error="""
       When constructing a VAGRANTFILE for the libvirt provider
       interface reuse is not possible because the UDP tunnels
       which libvirt uses for communication are point-to-point in
       nature. It is not possible to create a point-to-multipoint
       UDP tunnel!

       NOTE: Perhaps adding another switch to your topology would
       allow you to avoid reusing interfaces here.
"""

#Import the definitions file
if os.path.isfile(definition_file) and os.path.isfile("definitions.py"): 
    print "ERROR: Please use one definition file or the other!"
    print "    (either \"" +definition_file+ "\" or \"definitions.py\")"
    exit(1)

if os.path.isfile("definitions.py"):
    from definitions import *
    definition_file = "definitions.py"
elif os.path.isfile(definition_file):
    execfile(definition_file)
else:
    print "ERROR could not find definitions file! (either \"" +definition_file+ "\" or \"definitions.py\")"


###### Functions
def mac_fetch(hostname,mac_file,interface):
    global start_mac
    global mac_map
    global MGMT_Interface
    mac_string=""
    if interface != MGMT_Interface: return mac_string
    if hostname in mac_map: 
        mac_string=", :mac => \""+mac_map[hostname]+"\""
        mac_file.write(hostname+","+MGMT_Interface+","+mac_map[hostname]+"\n")
    else:
        new_mac = hex(int(start_mac, 16) + 1)[2:].upper()
        start_mac = new_mac
        mac_string=", :mac => \""+new_mac+"\""
        mac_file.write(hostname+","+MGMT_Interface+","+new_mac+"\n")
    return mac_string

def Generate_VM_Config(vfile,hostname,connection_map,hostname_code_mapper,mac_file):
    filtered_hostname=hostname.replace("-","_")
    vfile.write("  ##### DEFINE VM for "+hostname+" #####\n")
    vfile.write("  config.vm.define \"" + hostname + "\" do |" + filtered_hostname + "|\n")

    if provider == "virtualbox":
        vfile.write("      "+filtered_hostname+".vm.provider \"virtualbox\" do |v|\n")
        vfile.write("        v.name = \""+hostname+"\"\n")
    elif provider == "libvirt":
        vfile.write("\n      # disabling sync folder support on all VMs\n")
        vfile.write("      #   see note here: https://github.com/pradels/vagrant-libvirt#synced-folders\n")
        vfile.write("      "+filtered_hostname+".vm.synced_folder '.', '/vagrant', :disabled => true\n\n")
        vfile.write("      "+filtered_hostname+".vm.provider :libvirt do |v|\n")
    if hostname_code_mapper[hostname][0] == "switch":
        vfile.write("        v.memory = "+switch_mem+"\n")
    elif hostname_code_mapper[hostname][0] == "server":
        vfile.write("        v.memory = "+server_mem+"\n")
    vfile.write("      end\n")
    vfile.write("      "+filtered_hostname+".vm.hostname = \""+hostname+"\"\n")
    vfile.write("      "+filtered_hostname+".vm.box = \""+hostname_code_mapper[hostname][1]+"\"\n")


    
    vfile.write("\n")
    for (interface,net_number,line,line_number) in connection_map[hostname]:
        vfile.write("          # Local_Interface: "+interface+" Topology_File_Line("+line_number+"):"+line)
        mac_string="" #set to empty default
        if custom_mac and interface == MGMT_Interface:
            mac_string=mac_fetch(hostname,mac_file,interface)
        if provider == "virtualbox":
            net_name="net" + str(net_number)
            if hostname_code_mapper[hostname][0] == "server" or not configure_switch_interfaces:
                vfile.write("          "+filtered_hostname+".vm.network \"private_network\", virtualbox__intnet: '"+net_name+"', auto_config: false"+mac_string+"\n\n")
            else:
                vfile.write("          "+filtered_hostname+".vm.network \"private_network\", virtualbox__intnet: '"+net_name+"', cumulus__intname: '"+interface+"', auto_config: true"+mac_string+"\n\n")
        elif provider == "libvirt":
            src_port=net_number.split('-')[0]
            dst_port=net_number.split('-')[1]
            if hostname_code_mapper[hostname][0] == "server" or not configure_switch_interfaces:
                vfile.write("          "+filtered_hostname+".vm.network \"private_network\",\n")
                vfile.write("            :libvirt__tunnel_type => 'udp',\n")
                vfile.write("            :libvirt__tunnel_port => \"" + str(src_port) + "\",\n")
                vfile.write("            :libvirt__tunnel_local_port => \"" + str(dst_port) + "\",\n")
                vfile.write("            auto_config: false" +mac_string+"\n")

            else:
                vfile.write("          "+filtered_hostname+".vm.network \"private_network\",\n")
                vfile.write("            :libvirt__tunnel_type => 'udp',\n")
                vfile.write("            :libvirt__tunnel_port => \"" + str(src_port) + "\",\n")
                vfile.write("            :libvirt__tunnel_local_port => \"" + str(dst_port) + "\",\n")
                vfile.write("            auto_config: true" +mac_string+"\n")

    if synced_folder==False:
        vfile.write("      # Disabling the default synced folder\n")
        vfile.write("      "+filtered_hostname+".vm.synced_folder \".\", \"/vagrant\", disabled: true\n\n")

    if hostname in servers:
        vfile.write("      # SERVERS ONLY: Shorten Boot Process - remove \"Wait for Network\"\n")
        vfile.write("      "+filtered_hostname+".vm.provision :shell , inline: \"sudo sed -i 's/sleep [0-9]*/sleep 1/' /etc/init/failsafe.conf\"\n\n")

    vfile.write("      # Run Any Extra Config\n")
    if hostname == first_device_to_boot:
        vfile.write("      "+filtered_hostname+".vm.provision :shell , path: \""+script_storage+"/1st_device_config.sh\"\n\n")    
    elif hostname == second_device_to_boot :
        vfile.write("      "+filtered_hostname+".vm.provision :shell , path: \""+script_storage+"/2nd_device_config.sh\"\n\n")    
    elif hostname in servers:
        vfile.write("      "+filtered_hostname+".vm.provision :shell , path: \""+script_storage+"/extra_server_config.sh\"\n\n")    
    else:
        vfile.write("      "+filtered_hostname+".vm.provision :shell , path: \""+script_storage+"/extra_switch_config.sh\"\n\n")    

    if hostname_code_mapper[hostname][0] == "switch" or hostname in debian_host_remaps:
        vfile.write("      # Apply the interface re-map\n")
        vfile.write("      "+filtered_hostname+".vm.provision \"file\", source: \""+script_storage+"/rename_eth_swp\", destination: \"/home/vagrant/rename_eth_swp\"\n")
        vfile.write("      "+filtered_hostname+".vm.provision \"file\", source: \""+script_storage+"/autogenerated/"+hostname+"_remap_eth\", destination: \"/home/vagrant/remap_eth\"\n")
        vfile.write("      "+filtered_hostname+".vm.provision :shell , inline: \"mv /home/vagrant/rename_eth_swp /etc/init.d/rename_eth_swp\"\n")
        vfile.write("      "+filtered_hostname+".vm.provision :shell , inline: \"mv /home/vagrant/remap_eth /etc/default/remap_eth\"\n")
        vfile.write("      "+filtered_hostname+".vm.provision :shell , inline: \"chmod 755 /etc/init.d/rename_eth_swp\"\n")

#        if hostname_code_mapper[hostname][0] == "switch":
#            vfile.write("      "+filtered_hostname+".vm.provision \"file\", source: \""+script_storage+"/rename_eth_swp\", destination: \"/home/vagrant/rename_eth_swp\"\n")
        if hostname in debian_host_remaps and hostname_code_mapper[hostname][0] == "server":
            vfile.write("      "+filtered_hostname+".vm.provision :shell , inline: \"sudo sed -i '/exit 0/d' /etc/rc.local \"\n")
            vfile.write("      "+filtered_hostname+".vm.provision :shell , inline: \"sudo echo '/etc/init.d/rename_eth_swp start' >> /etc/rc.local \"\n")
            vfile.write("      "+filtered_hostname+".vm.provision :shell , inline: \"sudo echo 'exit 0' >> /etc/rc.local \"\n")

        vfile.write("      "+filtered_hostname+".vm.provision :shell , inline: \"/etc/init.d/rename_eth_swp verbose\"\n")

    if provider=="virtualbox":
        vfile.write("      "+filtered_hostname+".vm.provider \"virtualbox\" do |vbox|\n")
        count=1
        for (interface,net_name,line,line_number) in connection_map[hostname]:
            vfile.write("        vbox.customize ['modifyvm', :id, '--nicpromisc"+str(count+1)+"', 'allow-vms']\n")
            count +=1
        vfile.write("      end\n")
    vfile.write("  end\n\n")

def getKey(item):
    base = 10
    if item[0][0:3].lower() == "eth": base = 0
    val = float(item[0][3:].replace("s","."))
    return val + base

def remove_generated_files(hostname_code_mapper):
    if verbose: print "Removing existing REMAP FILES..."
    for hostname in hostname_code_mapper:
        if hostname_code_mapper[hostname][0]=="switch" or hostname in debian_host_remaps:
            if os.path.isfile(script_storage+"/autogenerated/"+hostname+"_remap_eth"):
                if verbose: print "     -" + script_storage+"/autogenerated/"+hostname+"_remap_eth" 
                os.remove(script_storage+"/autogenerated/"+hostname+"_remap_eth")
    files=os.listdir(script_storage+"/autogenerated/")
    for file in files:
        if file.endswith("_remap_eth"):
            if verbose: print "     -" + file 
            os.remove(script_storage+"/autogenerated/"+file)

def generate_shareable_zip():
    import zipfile
    files_to_zip=[os.path.split(definition_file)[1],"dhcp_mac_map",os.path.split(topology_file)[1],os.path.split(VAGRANTFILE)[1]]
    folders_to_zip=["./","./helper_scripts","./helper_scripts/autogenerated"]
    if os.path.split(topology_file)[0] not in folders_to_zip: folders_to_zip.append(os.path.split(topology_file)[0])
    if verbose: print "Creating ZIP..." 
    zf = zipfile.ZipFile(ZIPFILE, "w")
    for dirname, subdirs, files in os.walk("./"):
        if dirname in folders_to_zip:
            zf.write(dirname)
            for filename in files:
                if not filename.endswith("~"):
                    if filename in files_to_zip:
                        if verbose: print "  adding %s to zip..." % filename
                        zf.write(os.path.join(dirname, filename))
        else: 
            continue
    zf.close()

def generate_remapping_files(hostname_code_mapper,connection_map,debian_host_remaps):
    if verbose: print "GENERATING REMAP FILES..."
    for hostname in hostname_code_mapper:
        if hostname_code_mapper[hostname][0]=="switch" or hostname in debian_host_remaps:
            if verbose: print "    GENERATING REMAP FILE for " +hostname
            #We must create a remap file
            filename=script_storage+"/autogenerated/"+hostname+"_remap_eth"
            with open(filename,"wb") as remap_file:
                remap_file.write("""MAP="\n""")
                if use_vagrant_interface==True :
                    remap_file.write("""     eth0=vagrant\n""")
                count=1
                for (interface,net_name,line,line_number) in connection_map[hostname]:
                    remap_file.write("     eth"+str(count)+"="+interface+"\n")
                    count+=1
                remap_file.write("\"\n")


def parse_topology_file():
    global warning
    print "\n######################################"
    print "          Topology Converter"
    print "######################################"
    #Print collected Content from Definitions.py file
    print "\n\nSwitch OS will be: \"" + switch_code + "\""
    print "   On the following devices..."
    for device in switches:
        print "    * " + device
    print 
    print ""
    print "Server OS will be: \"" + server_code + "\""
    print "   On the following devices..."
    for device in servers:
        print "    * " + device

    #Open topology file
    with open(topology_file,"r") as f1:
        file_contents= f1.readlines()
    #Key is hostname, value is [(port,net_number,topo_line,topo_line_number)]
    ##### This could be done with a class
    connection_map=defaultdict(list)
    #Map Hostnames seen in Topology file to Hostnames defined in the Definitions.py File
    #Key is hostname, value is ("switch/server","box_vers_to_run")
    hostname_code_mapper={}
    
    #Parse Topology_File
    net_number=1
    line_number=0
    print "\n###############################"
    print "   Topology File Contents:"
    print "###############################"
    for line in file_contents:
        if verbose: print " Parsing line number: %s (%s)" % (line_number,line)
        if line_number == 0: line_number +=1; continue #Skip First line
        elif not re.match("^.* -- .*$",line): continue #Skip lines that do not fit format
        
        new_net=True
        if provider == "libvirt" and net_number == port_gap:
            print "ERROR: Port_Gap (in "+sys.argv[0]+") should be greater than the number of links in the topology!!!"
            exit(1)

        line_pieces=line.split("--")
        
        left_side=line_pieces[0].replace("\n","").replace(" ","").replace('"','')
        right_side=line_pieces[1].replace("\n","").replace(" ","").replace('"','')

        if left_side != "[EMPTY]":
            lhostname,linterface=left_side.split(":")
        if right_side != "[EMPTY]":
            rhostname,rinterface=right_side.split(":")

        #### Adding [EMPTY] Support checking
        if left_side == "[EMPTY]" and right_side == "[EMPTY]":
            warning=True
            print "WARNING: Topology File (Line %s) -- Both sides set to [EMPTY], skipping line." %(line_number)
            line_number +=1
            continue #Skip this line

        #check for hostname existance in definitions.py
        if left_side != "[EMPTY]":
            if lhostname in switches: hostname_code_mapper[lhostname]=("switch",switch_code)
            elif lhostname in servers: hostname_code_mapper[lhostname]=("server",server_code)
            elif lhostname in Fake_Devices: hostname_code_mapper[lhostname]=("faked_device","faked_device")
            else:
                print "\nERROR: We have found a Hostname (\""+lhostname+"\") in the Topology File that is not specified"
                print "       as a switch or server in the definitions.py file!"
                exit(1)
        if right_side != "[EMPTY]":
            if rhostname in switches: hostname_code_mapper[rhostname]=("switch",switch_code)
            elif rhostname in servers: hostname_code_mapper[rhostname]=("server",server_code)
            elif rhostname in Fake_Devices: hostname_code_mapper[rhostname]=("faked_device","faked_device")
            else:
                print "\nERROR: We have found a Hostname (\""+rhostname+"\") in the Topology File that is not specified"
                print "       as a switch or server in the definitions.py file!"
                exit(1)

        #check to see if interface/hostname combo has already been declared elsewhere
        left_exists = -1
        index=0
        if left_side != "[EMPTY]":
            if lhostname in connection_map:
                for link in connection_map[lhostname]:
                    if link[0] == linterface:
                        left_exists=index
                        new_net=False
                        #leftside interface already exists use his net_name
                        if provider=="libvirt":
                            print "ERROR: Topology File (Line %s) -- Interface %s%s is already used." %(line_number,lhostname,linterface)
                            print libvirt_reuse_error
                            exit(1)
                        warning=True
                        print "WARNING: Topology File (Line %s) -- Interface %s:%s is already used (this essentially creates a hub here)." %(line_number,lhostname,linterface)
                        net_name=link[1]
                    index+=1

        right_exists = -1
        index=0
        if right_side != "[EMPTY]":
            if rhostname in connection_map:
                for link in connection_map[rhostname]:
                    if link[0] == rinterface:
                        right_exists=index
                        if provider=="libvirt":
                            print "ERROR: Topology File (Line %s) -- Interface %s%s is already used." %(line_number,lhostname,linterface)
                            print libvirt_reuse_error
                            exit(1)
                        warning=True
                        print "WARNING: Topology File (Line %s) -- Interface %s:%s is already used (this essentially creates a hub here)." %(line_number,rhostname,rinterface)
                        if not new_net and net_name!=link[1]:
                            print "WARN: Both interfaces have already been used in the following topology file line:"
                            print "    " + line
                            print "   Move this line to the top of the topology file and try again."
                            exit(1)
                        new_net=False
                        #rightside interface already exists use his net_name
                        net_name=link[1]
                    index+=1

        #add interfaces to connection map
        if provider=="virtualbox":
            left_net=net_number
            right_net=net_number
        elif provider=="libvirt":
            PortA=str(start_port+net_number)
            PortB=str(start_port+port_gap+net_number)
            left_net=PortA+"-"+PortB
            right_net=PortB+"-"+PortA
        else:
            print "ERROR: Provider must be set to either \"virtualbox\" or \"libvirt\" in " + sys.argv[0]
            exit(1)
        if left_exists == -1 and left_side != "[EMPTY]": connection_map[lhostname].append([linterface,left_net,line,str(line_number)])
        else:
            connection_map[lhostname][left_exists][2] = "Multiple Lines Generated this Line\n"
            connection_map[lhostname][left_exists][3] = "multi"

        if right_exists == -1 and right_side != "[EMPTY]": connection_map[rhostname].append([rinterface,right_net,line,str(line_number)])
        else:
            connection_map[rhostname][right_exists][2] = "Multiple Lines Generated this Line\n"
            connection_map[rhostname][right_exists][3] = "multi"
    
        if lhostname in Fake_Devices:
            left_side +=" (Faked Device)"
        if rhostname in Fake_Devices:
            right_side +=" (Faked Device)"

        if provider == "virtualbox":
            net_name="net" + str(net_number)
            print "   "+net_name + "    " + left_side + " " + right_side
        elif provider == "libvirt":
            print "   (SOURCE UDP Port:" + str(start_port+net_number) + ") " + left_side + "  -- (SOURCE UDP Port:" + str(start_port+port_gap+net_number) + ") " + right_side

        if new_net: net_number +=1
        line_number +=1

    if warning:
        print "\n\n  **** WARNING!!! **** "
        print "             There are warnings above! LOOK AT THEM!<<<"  
        print "  **** WARNING!!! **** "

    #Sort the list for proper interface mapping
    for hostname in connection_map:
        connection_map[hostname].sort(key=getKey)
    if verbose:
        for hostname in connection_map:
            print "\nHostname: " + hostname
            print "  [PORT] -- [Net Number or UDP Port]"
            for (interface,net_number,line,line_number) in connection_map[hostname]:
                print "    " + interface + " -- " + str(net_number)
    return hostname_code_mapper,connection_map

def generate_vagrantfile(hostname_code_mapper,connection_map):
    global verbose
    #Build Vagrant_file for VirtualBox

    mac_file = open(dhcp_mac_file,"w")
    with open(VAGRANTFILE,"w") as vfile:
        vfile.write("# Created by Topology-Converter v"+version+"\n")
        vfile.write("#    using topology data from: "+topology_file+"\n")
        vfile.write("#    using definition data from: "+definition_file+"\n")
        vfile.write("#    NOTE: in order to use this Vagrantfile you will need:\n")
        #Variable Dependencies
        if provider == "virtualbox": vfile.write("#        -Virtualbox installed: https://www.virtualbox.org/wiki/Downloads \n")
        elif provider == "libvirt":
            vfile.write("#        -Libvirt Installed -- guide to come\n")
            vfile.write("#        -Boxes which have been mutated to support Libvirt -- see guide below:\n")
            vfile.write("#            https://community.cumulusnetworks.com/cumulus/topics/converting-cumulus-vx-virtualbox-vagrant-box-gt-libvirt-vagrant-box\n")
            vfile.write("#        -Start with \"vagrant up --provider libvirt --parallel\n")
        vfile.write("#        -Vagrant(v1.7+) installed: http://www.vagrantup.com/downloads \n")
        vfile.write("#        -Cumulus Plugin for Vagrant installed: $ vagrant plugin install vagrant-cumulus \n")
        vfile.write("#        -the \"helper_scripts\" directory that comes packaged with topology-converter.py \n")
        if generate_ansible_hostfile:
            vfile.write("#        -Ansible (v1.9+) installed: http://docs.ansible.com/ansible/intro_installation.html \n")
        vfile.write("""Vagrant.configure(\"2\") do |config|
  ##### GLOBAL OPTIONS #####"""+"\n")
        if provider == "virtualbox":
            vfile.write("""
  config.vm.provider \"virtualbox\" do |v|
    v.gui=false
  end""")
        elif provider == "libvirt":
            vfile.write("""  # increase nic adapter count to be greater than 8
  # for all VMs.
  config.vm.provider :libvirt do |domain|
    domain.nic_adapter_count = 55
  end
""")
        else:
            vfile.write("    # [NONE]")
        #If using ansible, we'll generate a hostfile
        if generate_ansible_hostfile:
            with open("./helper_scripts/empty_playbook.yml","w") as playbook:
                playbook.write("""---
- hosts: all
  user: vagrant
  tasks:
    - command: "uname -a"
""")
            with open("./ansible.cfg","w") as ansible_cfg:
                ansible_cfg.write("""[defaults]
inventory = ./.vagrant/provisioners/ansible/inventory/vagrant_ansible_inventory
hostfile= ./.vagrant/provisioners/ansible/inventory/vagrant_ansible_inventory
host_key_checking=False""")
            vfile.write("""
  #Generating Ansible Host File at following location:
  #    ./.vagrant/provisioners/ansible/inventory/vagrant_ansible_inventory
  config.vm.provision "ansible" do |ansible|
    ansible.playbook = "./helper_scripts/empty_playbook.yml"
  end""")
    
        vfile.write("\n  ##### DEFINE VMs #####\n")

        if first_device_to_boot != "":
            Generate_VM_Config(vfile,first_device_to_boot,connection_map,hostname_code_mapper,mac_file)
        if second_device_to_boot != "":
            Generate_VM_Config(vfile,second_device_to_boot,connection_map,hostname_code_mapper,mac_file)
        for hostname in servers:
            if first_device_to_boot == hostname: continue
            elif second_device_to_boot == hostname: continue
            elif hostname in connection_map:
                Generate_VM_Config(vfile,hostname,connection_map,hostname_code_mapper,mac_file)
            else:
                if verbose: print "Hostname %s which exists in server list is not found in topology file... skipping." % hostname
        for hostname in switches:
            if first_device_to_boot == hostname: continue
            elif second_device_to_boot == hostname: continue
            elif hostname in connection_map:
                Generate_VM_Config(vfile,hostname,connection_map,hostname_code_mapper,mac_file)
            else:
                if verbose: print "Hostname %s which exists in server list is not found in topology file... skipping." % hostname
            
        vfile.write("end\n")
    mac_file.close()
    if not custom_mac: os.remove(dhcp_mac_file)

def main():
    hostname_code_mapper,connection_map = parse_topology_file()

    if clean_up: remove_generated_files(hostname_code_mapper)

    generate_remapping_files(hostname_code_mapper,connection_map,debian_host_remaps)
    
    generate_vagrantfile(hostname_code_mapper,connection_map)

    generate_shareable_zip()



    
if __name__ == "__main__":
    main()
    print "\nVagrantfile has been generated!\n"
    if warning:
        print "\nDONE WITH ***WARNINGs***\n"
    else:
        print "\nDONE!\n"
exit(0)
