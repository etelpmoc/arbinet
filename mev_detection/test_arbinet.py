from gnn import *
import sys

if __name__ == "__main__":
    layer = sys.argv[1]

    if layer == "GCN":
        model = GCN(14, hidden_channels=512)
    if layer == "GAT":
        model = GAT(14, hidden_channels=512)
    if layer == "SAGE":
        model = SAGE(14, hidden_channels=512)

    model_path = f"pretrained_models/{layer}.pkl"
    model.load_state_dict(torch.load(model_path))

    test_data_path = "pretrained_models/test_dataset.pt"
    test_dataset = torch.load(test_data_path)
    test_loader = DataLoader(test_dataset, batch_size=1, shuffle=False)
    
    test(model, test_loader,0)
