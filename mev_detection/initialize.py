if __name__ == "__main__":
    with open("settings.py", 'w') as f:
        f.write("""DB_HOST=''\n""")
        f.write("""DB_USER=''\n""")
        f.write("""DB_PASSWORD=''\n""")
        f.write("""DB_NAME='MEV'\n""")
        f.write("""ERIGON_HOST=''\n""")
        f.write("""ERIGON_PORT=8545\n""")
        
