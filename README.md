# ArbiNet

This project is supported by Ethereum Grants Program. A paper will be published soon.

# Requirements

mev-detection-bot requires

#### 1. Erigon archive node with support for traces and receipts

#### 2. MySQL database to store preprocessed transactions

# Environment
- Ubuntu 20.04.5 LTS
- Pytorch 1.13.1 cpu
- Anaconda 4.10.3

To install torch and torch_geometric, install them with following command
```
# torch cpu
pip install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cpu

# torch geometric
pip install pyg-lib torch-scatter torch-sparse torch-cluster torch-spline-conv torch-geometric -f https://data.pyg.org/whl/torch-1.13.0+cpu.html

```


# Setup

1. Clone git project
```
git clone https://github.com/etelpmoc/mev-detection-bot.git
```

2. Make conda environement
```
conda create -n mev python=3.7.11
```

3. Install packages
```
cd mev-detection-bot
pip install -r requirements.txt
```

4. Initialize
```
python mev_detection/initialize.py
```

5. Enter your DB info and edit port number of Erigon node if necessary 
```
# mev_detection/settings.py
DB_HOST="~~"
DB_USER="~~"
DB_PASSWORD="~~"
DB_NAME="~~"
ERIGON_HOST="~~"
ERIGON_PORT=8545
```

# Preprocess transactions
```
python mev_detection/preprocess_transactions.py 15540000 15550000
```
- Store transactions in MySQL database

# Label transactions
```
python mev_detection/label_transactions.py 15540000 15550000
```

# Train model
```
python mev_detection/train_model.py gat(or gcn or sage)
```

# Performance
| Model  | Train Accuracy | Test Accuracy |
| ------------- | ------------- | ------------- |
| GCN  | 0.9965  | 0.9968  |
| GAT  | 0.9992  | 0.9991  |
| GraphSage  | 0.9985  | 0.9990  |
