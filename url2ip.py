import socket
website = "google.com"
print (f"""The IP for the {website} is: {socket.gethostbyname(website)}""")