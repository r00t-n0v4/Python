import rsa

with open("public.pem", "rb") as f:
    public_key = rsa.PublicKey.load_pkcs1(f.read())

with open("private.pem", "rb") as f:
    private_key = rsa.PrivateKey.load_pkcs1(f.read())

message = "what ever you make"

#encrypt
encrypted_message = rsa.encrypt(message.encode(), public_key)

with open("encrypted.message", "wb") as f:
    f.write(encrypted_message)

#decrypt
decryp_message = open("encrypted.message", "rb").read()

clear_message = rsa.decrypt(decryp_message, private_key)
print(clear_message.decode)