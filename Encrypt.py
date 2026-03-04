import crytography.fernet 
import Fernet

key = Fernet.generate_key()

with open('file.key', 'wb') as filekey:
	filekey.write(key)

with open('filekey.key', 'rb') as filekey:
    key = filekey.read()
 
# using the generated key
fernet = Fernet(key)
 
# opening the original file to encrypt
with open('nba.csv', 'rb') as file:
    original = file.read()
     
# encrypting the file
encrypted = fernet.encrypt(original)
 
# opening the file in write mode and
# writing the encrypted data
with open('.txt', 'wb') as encrypted_file:
    encrypted_file.write(encrypted)