import os
import phonenumbers
from phonenumbers import geocoder, carrier, timezone


print("--------------------------------------------------------------------------------------------------")
print("██████  ██   ██  ██████  ███    ██ ███████     ██████  ███████ ██    ██ ███████ ██████  ███████ ")
print("██   ██ ██   ██ ██    ██ ████   ██ ██          ██   ██ ██      ██    ██ ██      ██   ██ ██      ")
print("██████  ███████ ██    ██ ██ ██  ██ █████       ██████  █████   ██    ██ █████   ██████  ███████ ")
print("██      ██   ██ ██    ██ ██  ██ ██ ██          ██   ██ ██       ██  ██  ██      ██   ██      ██ ")
print("██      ██   ██  ██████  ██   ████ ███████     ██   ██ ███████   ████   ███████ ██   ██ ███████ ")
print("--------------------------------------------------------------------------------------------------")

number = input('What is the phone number (add +1 if canada): ')
phone_number = phonenumbers.parse(number)
print(geocoder.description_for_number(phone_number, 'en'))
print(carrier.name_for_number(phone_number, 'en'))
print(timezone.time_zones_for_number(phone_number))