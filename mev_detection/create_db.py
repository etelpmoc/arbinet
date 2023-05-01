from settings import *
import pymysql

if __name__ == "__main__":
    # Connect to MySQL server
    mydb = pymysql.connect(
    host=DB_HOST,
    user=DB_USER,
    password=DB_PASSWORD,
    )
    mycursor = mydb.cursor()

    try:
        mycursor.execute(f"CREATE DATABASE {DB_NAME}")
    except:
        pass
    

    try:
        mycursor.execute(f"CREATE TABLE MEV.`labeled_arbitrages` (`block` int DEFAULT NULL,`tx_hash` varchar(70) NOT NULL,`taker_address` varchar(45) DEFAULT NULL, `platforms` json DEFAULT NULL,PRIMARY KEY (`tx_hash`)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci")
    
    except:
        pass

