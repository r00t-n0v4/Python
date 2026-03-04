import hashlib

password = "dc647eb65e6711e155375218212b3964"
md5 = hashlib.md5(password.decode())

print(md5.hexdigest());