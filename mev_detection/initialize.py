import os

if __name__ == "__main__":
    if "settings.py" not in os.listdir('.'):
        with open("settings.py", 'w') as f:
            f.write("""DB_HOST=''\n""")
            f.write("""DB_USER=''\n""")
            f.write("""DB_PASSWORD=''\n""")
            f.write("""DB_NAME='MEV'\n""")
            f.write("""ERIGON_HOST=''\n""")
            f.write("""ERIGON_PORT=8545\n""")
    
    if "custom_models" not in os.listdir('.'):
        os.mkdir("custom_models")
