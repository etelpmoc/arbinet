import torch
from torch_geometric.loader import DataLoader
from torch.nn import Linear
from torch_geometric.nn import GCNConv, GATv2Conv, SAGEConv 
from torch_geometric.nn import global_mean_pool
from torch_geometric.data import Data


class GAT(torch.nn.Module):
    def __init__(self, input_features,hidden_channels):
        super(GAT, self).__init__()
        torch.manual_seed(12345)
        self.conv1 = GATv2Conv(input_features, hidden_channels)
        self.conv2 = GATv2Conv(hidden_channels, hidden_channels)
        self.conv3 = GATv2Conv(hidden_channels, hidden_channels)
        self.conv4 = GATv2Conv(hidden_channels, hidden_channels)
        self.lin = Linear(hidden_channels, 256)
        self.lin2 = Linear(256, 2)
        
    def forward(self, x, edge_index, edge_weight,  batch):
        # 1. Obtain node embeddings 
        x = self.conv1(x, edge_index)
        x = x.relu()
        
        x = self.conv2(x, edge_index)
        x = x.relu()
        
        x = self.conv3(x, edge_index)
        
        # 2. Readout layer
        x = global_mean_pool(x, batch)

        # 3. Apply a final classifier
        x = self.lin(x)
        
        if batch is not None and not torch.all(batch.eq(0)):
            x = torch.nn.BatchNorm1d(256)(x)
        
        x = x.relu()
        x = self.lin2(x)
        return x

class GCN(torch.nn.Module):
    def __init__(self, input_features, hidden_channels):
        super(GCN, self).__init__()
        torch.manual_seed(12345)
        self.conv1 = GCNConv(input_features, hidden_channels)
        self.conv2 = GCNConv(hidden_channels, hidden_channels)
        self.conv3 = GCNConv(hidden_channels, hidden_channels)
        self.conv4 = GCNConv(hidden_channels, hidden_channels)
        self.lin = Linear(hidden_channels, 256)
        self.lin2 = Linear(256, 2)
        
    def forward(self, x, edge_index, edge_weight,  batch):
        # 1. Obtain node embeddings 
        x = self.conv1(x, edge_index)
        x = x.relu()
        x = self.conv2(x, edge_index)
        x = x.relu()
        x = self.conv3(x, edge_index)
        
        # 2. Readout layer
        x = global_mean_pool(x, batch)

        # 3. Apply a final classifier
        x = self.lin(x)
        if batch is not None and not torch.all(batch.eq(0)):
            x = torch.nn.BatchNorm1d(256)(x)
        x = x.relu()
        x = self.lin2(x)
        return x
    
class GraphSAGE(torch.nn.Module):
    def __init__(self,input_features, hidden_channels):
        super(GraphSAGE, self).__init__()
        torch.manual_seed(12345)
        self.conv1 = SAGEConv(input_features, hidden_channels)
        self.conv2 = SAGEConv(hidden_channels, hidden_channels)
        self.conv3 = SAGEConv(hidden_channels, hidden_channels)
        self.conv4 = SAGEConv(hidden_channels, hidden_channels)
        self.lin = Linear(hidden_channels, 256)
        self.lin2 = Linear(256, 2)
        
    def forward(self, x, edge_index, edge_weight,  batch):
        # 1. Obtain node embeddings 
        edge_index = edge_index.type(torch.int64) 
        x = self.conv1(x, edge_index)
        x = x.relu()
        x = self.conv2(x, edge_index)
        x = x.relu()
        x = self.conv3(x, edge_index)
        
        # 2. Readout layer
        x = global_mean_pool(x, batch)

        # 3. Apply a final classifier
        x = self.lin(x)
        if batch is not None and not torch.all(batch.eq(0)):
            x = torch.nn.BatchNorm1d(256)(x)
            
        x = x.relu()
        x = self.lin2(x)
        return x

def train(mod, loader, optimizer, criterion,debug=0):
    mod.train()
    for data in loader:  
        optimizer.zero_grad()
        out = mod(data.x, data.edge_index, data.edge_weight, data.batch)
        
        pred = out.argmax(dim=1)
        if pred.size(0) != data.y.size(0):
            continue
        if debug:
            for idx in np.where(torch.eq(pred,data.y)==False)[0]:
                print(pred[idx], data.tx[idx],data.y[idx])
        loss = criterion(out, data.y)  
        loss.backward()
        optimizer.step()

def test(mod, loader, debug=0):
    mod.eval()
    correct = 0
    
    TP = 0
    FP = 0
    FN = 0
    TN = 0
    
    for data in loader: 
        out = mod(data.x, data.edge_index, data.edge_weight, data.batch)  
        pred = out.argmax(dim=1) 
        if pred.size(0) != data.y.size(0):
            continue
        
        positive_class = 1
        TP += ((pred == positive_class) & (data.y == positive_class)).sum().item()
        FP += ((pred == positive_class) & (data.y != positive_class)).sum().item()
        FN += ((pred != positive_class) & (data.y == positive_class)).sum().item()
        TN += ((pred != positive_class) & (data.y != positive_class)).sum().item()
        
        if debug:
            for idx in np.where(torch.eq(pred,data.y)==False)[0]:
                print("wrong",pred[idx], data.tx[idx],data.y[idx])
        correct += int((pred == data.y).sum())  
    if debug: 
        print(len(loader.dataset)-correct, " wrong classifcation out of total :", len(loader.dataset))
    
    # Calculate precision, recall, and F1-score for the positive class
    if TP + FP > 0:
        precision = TP / (TP + FP)
    else:
        precision = 0

