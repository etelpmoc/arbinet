import pymysql
import random
import sys
from web3 import Web3
from settings import *
from sqlalchemy import create_engine
import pandas as pd
import torch
import json
from torch_geometric.data import Data
from torch_geometric.loader import DataLoader
from torch.nn import Linear
import torch.nn.functional as F
from torch_geometric.nn import GCNConv, GATv2Conv, SAGEConv
from torch_geometric.nn import global_mean_pool 

def add_features(total_transfer, tx, from_addr, to_addr, blockNum):
    nodes_dict, tokens_dict = {}, {}
    edge_start, edge_end = [], []
    
    zero_amount = []
    for idx,transfer in enumerate(total_transfer):
        if transfer[3] not in tokens_dict.keys():
            if transfer[2] != 0:
                tokens_dict[transfer[3]] = len(tokens_dict)
            else:
                zero_amount.append(idx)
                continue
        if transfer[0] not in nodes_dict.keys():
            nodes_dict[transfer[0]] = len(nodes_dict)
        if transfer[1] not in nodes_dict.keys():
            nodes_dict[transfer[1]] = len(nodes_dict)
            
        edge_start.append(nodes_dict[transfer[0]])
        edge_end.append(nodes_dict[transfer[1]])
        
    for k in sorted(zero_amount, reverse=True):
        print(total_transfer[k])
        del total_transfer[k]   

    profits = [[0 for y in range(len(tokens_dict))  ] for x in range(len(nodes_dict))]
    trade_bool_send = [[0 for y in range(len(tokens_dict))  ] for x in range(len(nodes_dict))]
    trade_bool_receive = [[0 for y in range(len(tokens_dict))  ] for x in range(len(nodes_dict))]
    trade_num_send = [[0 for y in range(len(tokens_dict))  ] for x in range(len(nodes_dict))]
    trade_num_receive = [[0 for y in range(len(tokens_dict))  ] for x in range(len(nodes_dict))]
    
    max_transfer = [0 for x in range(len(tokens_dict))]
    for transfer in total_transfer:
        profits[nodes_dict[transfer[0]]][tokens_dict[transfer[3]]] -= transfer[2]
        profits[nodes_dict[transfer[1]]][tokens_dict[transfer[3]]] += transfer[2]
        
        trade_num_send[nodes_dict[transfer[0]]][tokens_dict[transfer[3]]] += 1
        trade_num_receive[nodes_dict[transfer[0]]][tokens_dict[transfer[3]]] += 1
        
        trade_bool_send[nodes_dict[transfer[0]]][tokens_dict[transfer[3]]] = 1
        trade_bool_receive[nodes_dict[transfer[1]]][tokens_dict[transfer[3]]] = 1
        
        if transfer[2] > max_transfer[tokens_dict[transfer[3]]]:
            max_transfer[tokens_dict[transfer[3]]] = transfer[2]
        
    for addridx, addr in enumerate(profits):
        for idx,profit in enumerate(addr):
            if profit < 0:
                if -profit*10000 > max_transfer[idx]:
                    profits[addridx][idx] = -1
                else:
                    profits[addridx][idx] = 0
            elif profit == 0:
                profits[addridx][idx] = 0
            else:
                if profit*10000 < max_transfer[idx]:
                    profits[addridx][idx] = 0
                else:
                    profits[addridx][idx] = 1

        if -1 in profits[addridx]:
            profits[addridx] = [-1,1]
        elif sum(profits[addridx]) == 0:
            profits[addridx] = [0, 1]
        else:
            profits[addridx] = [1, 1]
            
        # trade boolean
        profits[addridx].append(sum(trade_bool_send[addridx]))
        profits[addridx].append(sum(trade_bool_receive[addridx]))
        
        # trade num
        profits[addridx].append(sum(trade_num_send[addridx]))
        profits[addridx].append(sum(trade_num_receive[addridx]))
    try:
        profits[nodes_dict["0x0000000000000000000000000000000000000000"]][1] = 0
    except:
        pass
    
    for node,idx in nodes_dict.items():
        if w3.eth.getCode(w3.toChecksumAddress(node)).hex() == "0x":
            profits[idx].append(0)
        else:
            profits[idx].append(1)
        if node == from_addr:
            profits[idx].append(1)
        else:
            profits[idx].append(0)
        if node == to_addr:
            profits[idx].append(1)
        else:
            profits[idx].append(0)    
        
        profits[idx].append(len(tokens_dict))
        
    x = torch.tensor(profits).float()
    
    edge_index = torch.tensor([edge_start, edge_end])
    
    y          = torch.tensor([target])
    
    data = Data(x=x, edge_index=edge_index, y=y, tx = tx)
    return data

class GNN(torch.nn.Module):
    def __init__(self, layer, hidden_channels):
        super(GNN, self).__init__()
        torch.manual_seed(12345)
        if layer == "gcn":
            self.conv1 = GCNConv(10, hidden_channels)
            self.conv2 = GCNConv(hidden_channels, hidden_channels)
            self.conv3 = GCNConv(hidden_channels, hidden_channels)
            self.conv4 = GCNConv(hidden_channels, hidden_channels)
        if layer == "gat":
            self.conv1 = GATv2Conv(10, hidden_channels)
            self.conv2 = GATv2Conv(hidden_channels, hidden_channels)
            self.conv3 = GATv2Conv(hidden_channels, hidden_channels)
            self.conv4 = GATv2Conv(hidden_channels, hidden_channels)
        if layer == "sage":
            self.conv1 = SAGEConv(10, hidden_channels)
            self.conv2 = SAGEConv(hidden_channels, hidden_channels)
            self.conv3 = SAGEConv(hidden_channels, hidden_channels)
            self.conv4 = SAGEConv(hidden_channels, hidden_channels)
        self.lin = Linear(hidden_channels, 256)
        self.lin2 = Linear(256, 2)
        
    def forward(self, x, edge_index, edge_weight,  batch):
        # 1. Obtain node embeddings 
        x = self.conv1(x, edge_index)
        x = x.relu()
        x = self.conv2(x, edge_index)
        x = x.relu()
        x = self.conv3(x, edge_index)
        x = x.relu()
        x = self.conv4(x, edge_index)
        
        # 2. Readout layer
        x = global_mean_pool(x, batch)

        # 3. Apply a final classifier
#         x = F.dropout(x, p=0.2, training=self.training)
        x = self.lin(x)
        x = torch.nn.BatchNorm1d(256)(x)
        x = x.relu()
        x = self.lin2(x)
        return x

def train(debug=0):
    model.train()
    for data in train_loader:  
        optimizer.zero_grad()
        out = model(data.x, data.edge_index, data.edge_weight, data.batch)
        
        pred = out.argmax(dim=1)
        if debug:
            for idx in np.where(torch.eq(pred,data.y)==False)[0]:
                print(pred[idx], data.tx[idx],data.y[idx])
        loss = criterion(out, data.y)  
        loss.backward()
        optimizer.step()

def test(loader, debug=0):
    model.eval()
    correct = 0
    for data in loader: 
        out = model(data.x, data.edge_index, data.edge_weight, data.batch)  
        pred = out.argmax(dim=1) 
        if debug:
            for idx in np.where(torch.eq(pred,data.y)==False)[0]:
                print("wrong",pred[idx], data.tx[idx],data.y[idx])
            # correct
            print("correct")
            for idx in np.where(torch.eq(pred,data.y)==True)[0]:
                print(pred[idx], data.tx[idx],data.y[idx])
        correct += int((pred == data.y).sum())  
    return correct / len(loader.dataset) 

if __name__ == "__main__":
    w3 = Web3(Web3.HTTPProvider(f"""http://localhost:{ERIGON_PORT}"""))
    layer = sys.argv[1]
    print(layer)
    assert(layer in ["gcn", "gat", "sage"])
    
    # Connect to DB
    db_connection_str = f"""mysql+pymysql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/Ethereum"""
    db_connection = create_engine(db_connection_str)
    start = 15537300
    end = 15550000

    transactions  = pd.read_sql(f'SELECT * FROM transactions_preprocessed WHERE Block_Number >= {start} and Block_Number <= {end}', con=db_connection)
    mev  = pd.read_sql(f'SELECT * FROM definedMEV WHERE Block_Number >= {start} and Block_Number <= {end}', con=db_connection)
    
    # Shuffle
    transactions = transactions.sample(frac=1)
    mev_txs = mev['Transaction_Hash']

    data_list = []

    count_mev = len(mev)
    count_non_mev = 0

    for _,row in transactions.iterrows():
        total_transfer = json.loads(row['Total_Transfer'])
        tx = row['Transaction_Hash']
    
        if  tx in mev_txs.values:
            target = 1
        else:
            if count_non_mev == count_mev:
                continue
            target = 0
            count_non_mev += 1
    
        tx_info = w3.eth.getTransaction(tx)
        if tx_info['value'] < 10**9 and tx_info['value']>0: 
            for idx, transfer in enumerate(total_transfer):
                if transfer[2] == tx_info['value'] and transfer[0] == tx_info['from'].lower():
                    del total_transfer[idx]
                    break
        
        from_addr = tx_info['from'].lower()
        try:
            to_addr = tx_info['to'].lower()
        except:
            count_non_mev -= 1
            continue
        blockNum = tx_info['blockNumber']
    
        print(count_non_mev, count_mev)
    
        data = add_features(total_transfer, tx, from_addr, to_addr, blockNum)
        data_list.append(data)
    
    random.shuffle(data_list)
    
    train_data_size = int(len(data_list)*0.8)

    train_loader = DataLoader(data_list[:train_data_size], batch_size=256, shuffle=True)
    test_loader = DataLoader(data_list[train_data_size:], batch_size=256, shuffle=False) 


    model = GNN(layer="gat",hidden_channels=512)
    print(model)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.0001, weight_decay=0)
    criterion = torch.nn.CrossEntropyLoss()

    for epoch in range(1, 201):
        train()
        train_acc = test(train_loader)
        test_acc = test(test_loader)
        print(f'Epoch: {epoch:03d}, Train Acc: {train_acc:.4f}, Test Acc: {test_acc:.4f}')
