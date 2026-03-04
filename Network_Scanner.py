import scapy.all as scapy
# We need to create regular expressions to ensure that the input is correctly formatted.
import re

print('-'*200)
print(' _______          __                       __       _________                                         ')
print(' \      \   _____/  |___  _  _____________|  | __  /   _____/ ____ _____    ____   ____   ___________ ')
print(' /   |   \_/ __ \   __\ \/ \/ /  _ \_  __ \  |/ /  \_____  \_/ ___\\__  \  /    \ /    \_/ __ \_  __ \ ')
print('/    |    \  ___/|  |  \     (  <_> )  | \/    <   /        \  \___ / __ \|   |  \   |  \  ___/|  | \/')
print('\____|__  /\___  >__|   \/\_/ \____/|__|  |__|_ \ /_______  /\___  >____  /___|  /___|  /\___  >__|   ')
print('        \/     \/                              \/         \/     \/     \/     \/     \/     \/       ')
print('-'*200)
print("""
Please enter an the IP range required (ex 192.168.1.0/24)
IP can be found using commands such as: 
Windows : ipconfig (find the adapter you want to see on)
mac/linux: ifconfig (find the adapter you want to see on)
When in doubt for the range use: https://creaclick.net/ipcalc
""")

# Regular Expression Pattern to recognise IPv4 addresses.
ip_add_range_pattern = re.compile("^(?:[0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]*$")

# Get the address range to ARP
while True:
    ip_add_range_entered = input("\nPlease enter the ip address and range that you want to send the ARP request to (ex 192.168.1.0/24): ")
    if ip_add_range_pattern.search(ip_add_range_entered):
        print(f"{ip_add_range_entered} is a valid ip address range")
        break


# Try ARPing the ip address range supplied by the user. 
# The arping() method in scapy creates a pakcet with an ARP message 
# and sends it to the broadcast mac address ff:ff:ff:ff:ff:ff.
# If a valid ip address range was supplied the program will return 
# the list of all results.
arp_result = scapy.arping(ip_add_range_entered)