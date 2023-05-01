from gnn import * 
import sys

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

    if TP + FN > 0:
        recall = TP / (TP + FN)
    else:
        recall = 0

    if precision + recall > 0:
        f1 = 2 * precision * recall / (precision + recall)
    else:
        f1 = 0
    
    if debug:
        print(f"""TP : {TP}, FP : {FP}""")
        print(f"""FN : {FN}, TN : {TN}""")
        
    return correct / len(loader.dataset) , precision, recall, f1

if __name__ == "__main__":
    layer = sys.argv[1]

    train_dataset = torch.load('pretrained_models/train_dataset.pt')
    test_dataset  = torch.load('pretrained_models/test_dataset.pt')
   
    # train_dataset : 91393, test_dataset : 96484 
    # To train fast with low performance, you can load data with smaller data
    # e.g. train_dataset[:20000],  test_dataset[:20000]
    train_loader = DataLoader(train_dataset, batch_size=256, shuffle=True)
    test_loader = DataLoader(test_dataset, batch_size=1, shuffle=False)    
    
    if layer == "GAT":
        model = GAT(14, hidden_channels=512)
    elif layer == "GCN":
        model = GCN(14, hidden_channels=512)
    elif layer == "SAGE":
        model = GraphSAGE(14, hidden_channels=512)

    optimizer = torch.optim.Adam(model.parameters(), lr=0.0001, weight_decay=0)
    criterion = torch.nn.CrossEntropyLoss(torch.tensor([1, 1], dtype=torch.float))
    
    max_f1 = 0
    for epoch in range(1,41):
        print(f"Epoch {epoch} starts")
        train(model, train_loader, optimizer, criterion)
        train_acc,_,_,_ = test(model,train_loader,0)       
        test_acc, precision, recall, f1 = test(model, test_loader,0)
        print(f'Epoch: {epoch:03d}, Train Acc: {train_acc:.4f}, Test Acc: {test_acc:.4f}')

        if f1 > max_f1 and epoch >= 5:
            max_f1 = f1
            # Save model and results
            torch.save(model.state_dict(), f"custom_models/{model}.pkl")
