#phone_info.py
#find info from a phone number

import phonenumbers
from phonenumbers import carrier, geocoder, timezone

mobileNum = input("enter phone number: ")
mobileNum = phonenumbers.parse(mobileNum)

with open(f"{mobileNum}.txt", 'w') as f:
    f.write(geocoder.description_for_number(mobileNum, 'en'))
    print(geocoder.description_for_number(mobileNum, 'en'))
    f.write(carrier.name_for_number(mobileNum, 'en'))
    print(carrier.name_for_number(mobileNum, 'en'))
    f.write(timezone.time_zones_for_number(mobileNum))
    print(timezone.time_zones_for_number(mobileNum))
f.close()