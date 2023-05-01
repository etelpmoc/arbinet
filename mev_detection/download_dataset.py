import requests

datasets = ['train_dataset.pt', 'test_dataset.pt']
for dataset in datasets:
    url = f"https://dl.dropboxusercontent.com/s/to8wfuwc0y8z72d/{dataset}"
    output_file = f"pretrained_models/{dataset}"

    response = requests.get(url)
    with open(output_file, "wb") as f:
        f.write(response.content)
