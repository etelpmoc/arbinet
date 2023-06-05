# ArbiNet

ArbiNet is the MEV detection model that doesn't require knowledge about DeFi smart contracts. 

We trained our model using the block #15,540,000 ~ # 15,585,000 , with our own labeled data.

All stuffs are open : Pretrained GNN-based model (.pkl files) , training/test dataset, code for training model, code for labeling MEV.

**(Updated) + All labeled MEV transactions data will be open in a few weeks!**

## Requirements

ArbiNet requires :

#### 1. Erigon archive node with support for traces and receipts

#### 2. (Not Necessary) MySQL database to store preprocessed transactions. 
- MySQL is only needed when you want to generate training data and test data from scratch. 
- Train and test data is provided in mev-detection/pretrain_models/

## Environment
- Ubuntu 20.04.5 LTS
- Pytorch 1.13.1 cpu
- Anaconda 4.10.3

To install torch and torch_geometric, install them with following command
```
### torch cpu
pip install torch torchvision torchaudio --extra-index-url https://download.pytorch.org/whl/cpu

### torch geometric
pip install pyg-lib torch-scatter torch-sparse torch-cluster torch-spline-conv torch-geometric -f https://data.pyg.org/whl/torch-1.13.0+cpu.html

```

## Setup

1. Clone git project
```
git clone https://github.com/etelpmoc/arbinet.git
```

2. Make conda environement
```
conda create -n mev python=3.7.11
```

3. Install packages
```
pip install -r requirements.txt
```

4. Initialize (for configuring Erigon Archive node and MySQL DB)
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


## Usage
This repository supports 3 levels of actions as follows. 

(1 may be the one you are looking for / 2 and 3 are time consuming, resource consuming) 

1. Using pretrained ArbiNet for detecting sandwich, arbitrage

2. Training ArbiNet with your own GNN parameter settings (given train,test data)

3. Constructing training dataset and test dataset from scratch


### 1. Use Pretrained model

Inspecting block 17167403 
```
./arbinet.sh 17167403
```
returns
```
Inspecting Block #17167403..🤔
Sandwiches
-> Frontrun : 0x8c6b406617861ddbff8b09b74af5533502eea8e41d8ff84ee75287c761ebf357,
-> Backrun  : 0xd5e131d3fa2a728c43e1bf45fb787cca75e1c147f53f17f4a5a13b21572d60cf
Arbitrages
-> 0xf3e455bd2fb0bc6da000daf921b99d69e28e049e52dc666ae27718d5eeae3c7f
-> 0x4781dd06f5af3ce6d27c88c6d472662f80bb2bd0dbe7eb1bdb327eeb8a5e24a7
-> 0x46e61d5e7a992b21944c43cb93f28ce9fcfc1f28c889878c1ff2fdff73f47359
```

Inspecting blocks from 17000000 to 17000010
```
./arbinet.sh 17000000 17000011
```

### 2. Train ArbiNet with your own parameter settings

To train ArbiNet in your own, you should get train data and test data from our open Dropbox cloud. (110MB each)

You can download data by 
```
cd mev_detection
python download_dataset.py
```
You can see train_dataset.pt, test_dataset.pt in pretrained_models/ .
Or you can download manually from our [google drive folder](https://drive.google.com/drive/folders/1M36tcAqObNo1gPzJ5_Z_QtNrqprj6V1s?usp=sharing).

To get data, simply train model with

```
python train_arbinet.py GAT
```
Supported GNN layers are GAT, GCN, GraphSAGE. 

To change parameter settings, you can modify train_arbinet.py.
For example, in train_arbinet.py
```
~~
optimizer = torch.optim.Adam(model.parameters(), lr=0.0001, weight_decay=0)
criterion = torch.nn.CrossEntropyLoss(torch.tensor([1, 1], dtype=torch.float))
~~
```
Modify learning rate, optimizer, loss functions, weight decay, and so on.

To change layers, modify gnn.py. Add or remove layers, change number of hidden states, pooling layer, and so on.
```
# gnn.py
...
class GAT(torch.nn.Module):
    def __init__(self, input_features,hidden_channels):
        super(GAT, self).__init__()
        torch.manual_seed(12345)
        self.conv1 = GATv2Conv(input_features, hidden_channels)
        self.conv2 = GATv2Conv(hidden_channels, hidden_channels)
...
```
Your models will be saved in custom_models/ .


To test model performance,
```
python test_arbinet.py
```

### 3. Constructing training dataset and test dataset from scratch

To construct dataset, first make empty databases and tables
```
cd mev_detection
python create_db.py
```

Add arbitrages and sandwicihes to database
```
python label_arbitrages.py 15500000 15900000
```
This might take a few hours to a few days depending on your I/O, node speed, CPU performance.

```
python label_sandwich.py 15500000 15900000
```

Add token transfer data to database (which will be used for graph construction)

```
python preprocess_transactions.py 15500000 15590000
```




(Train : 15540000 ~ 15585000 balanced data)
(Test  : 15585000 ~ 15590000 unbalanced data which is actual block data)

# Performance
| Model  | Train F1 | Test F1 |
| ------------- | ------------- | ------------- |
| GCN  | 0.9934  | 0.9659  |
| GAT  | 0.9974  | 0.9805  |
| GraphSage  | 0.9956  | 0.9814  |
