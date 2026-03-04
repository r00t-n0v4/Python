import ipinfo

access_token = 'c10f830e728ec5'
handler = ipinfo.getHandler(access_token)
ip_address = '171.244.0.91'
details = handler.getDetails(ip_address)
print(details.all)