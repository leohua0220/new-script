import os
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
from torchvision import transforms as T
from torch.utils.tensorboard import SummaryWriter
from other.try_3d.SCPTHDataset import SCPTHDataset
from other.try_3d.transform3d import ToTensor
from scripts.utils.load_save_models import save_checkpoint, get_latest_checkpoint, inference, load_checkpoint
# from scripts.utils.visualizer import visualize_predictions, visualize_dataloader
import open3d as o3d
from other.try_3d.utils_voxel_new import visualize_labels_as_voxels
CUDA_LAUNCH_BLOCKING=1
# Set CUDA_LAUNCH_BLOCKING for accurate stack trace
os.environ['CUDA_LAUNCH_BLOCKING'] = '1'

# Set device
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')

# Clear GPU cache
torch.cuda.empty_cache()

# Set PYTORCH_CUDA_ALLOC_CONF to manage memory fragmentation
os.environ['PYTORCH_CUDA_ALLOC_CONF'] = 'max_split_size_mb:128'

# Paths to dataset and split files
data_dir = 'dataset/3d_data'
train_split_file = 'dataset/splits/nvs_sem_train.txt'
val_split_file = 'dataset/splits/nvs_sem_val.txt'

# Define the transforms
transform = T.Compose([
    ToTensor(),
    # Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225])
])

# Create datasets and dataloaders
train_dataset = SCPTHDataset(data_dir, train_split_file, transform=transform)
val_dataset = SCPTHDataset(data_dir, val_split_file, transform=transform)

# Get length of datasets
train_len = len(train_dataset)
val_len = len(val_dataset)
print('Train dataset length:', train_len)
print('Val dataset length:', val_len)

#
# # check a random sample's shape:
# idx = torch.randint(0, train_len, (1,)).item()
# sample = train_dataset[idx]
# print(f'Random sample shape: {idx}', sample['depth'].shape)
batch_size = 1
train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, num_workers=8)
val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False, num_workers=8)


# check if the dataloader's shapes are correct, including the batch size
print('Train dataloader coords shape:', next(iter(train_loader))['coords'].shape)
print('Train dataloader labels shape:', next(iter(train_loader))['labels'].shape)
print('Val dataloader coords shape:', next(iter(val_loader))['coords'].shape)
print('Val dataloader labels shape:', next(iter(val_loader))['labels'].shape)

from other.try_3d.utils_voxel_new import SimpleSpConvNet

# Clear GPU cache
torch.cuda.empty_cache()

model3d = SimpleSpConvNet()

# model to device
model3d = model3d.to(device)

# Define the ignore index for invalid labels
IGNORE_INDEX = -1

# Define loss function and optimizer
criterion = nn.CrossEntropyLoss(ignore_index=IGNORE_INDEX)

optimizer = optim.Adam(model3d.parameters(), lr=0.001, weight_decay=1e-5)

# Check the model architecture
# print(model3d)
# Initialize TensorBoard SummaryWriter
writer = SummaryWriter(log_dir='./runs')
from scripts.utils.load_save_models import get_latest_checkpoint
# Create the checkpoints directory
checkpoint_dir = './checkpoints'

# Load latest checkpoint if available
# latest_checkpoint = get_latest_checkpoint(checkpoint_dir)
latest_checkpoint = False
start_epoch = 0
if latest_checkpoint:
    start_epoch, _ = load_checkpoint(latest_checkpoint, model3d, optimizer)
    print(f"Resuming training from epoch {start_epoch}")

import torch
# import torch.nn.functional as F
# from scripts.networks.utils_projection import project_to_3d
# # from scripts.networks.utils_projection import apply_softmax, colorize_point_cloud, save_point_cloud_to_ply,load_palette
from other.try_3d.utils_voxel_new import PC2Tensor


# 定义计算准确率的函数
def calculate_accuracy(outputs, labels, ignore_index):
    # 获取预测的标签
    preds = torch.argmax(outputs, dim=1)
    valid_mask = labels != ignore_index
    correct = torch.sum(preds[valid_mask] == labels[valid_mask]).item()
    total = torch.sum(valid_mask).item()
    return correct / total if total > 0 else 0

import spconv.pytorch as spconv
# Training loop
num_epochs = 500
save_interval = 10
best_val_loss = float('inf')
for epoch in range(start_epoch, num_epochs):

    model3d.train()
    running_loss = 0.0
    running_corrects = 0
    total_samples = 0
    for i, pc in enumerate(train_loader):
        coords = pc['coords'].to(device)
        labels = pc['labels'].to(device)
        # Add an extra dimension to labels to make its shape [1, 1203566, 1]
        labels = labels.unsqueeze(-1)
        invalid_mask = (labels < 0)
        labels[invalid_mask] = IGNORE_INDEX
        # # Concatenate along the last dimension
        inputs = torch.cat((coords, labels), dim=-1)

        spatial_shape = [20, 40, 40]
        pc2tensor = PC2Tensor(device, spatial_shape)
        spconv_tensor = pc2tensor(inputs)

        # label_spconv_tensor = spconv_tensor.features
        labels_sparse_tensor = spconv.SparseConvTensor(
            spconv_tensor.features, spconv_tensor.indices, spconv_tensor.spatial_shape, spconv_tensor.batch_size
        )
        optimizer.zero_grad()
        output = model3d(spconv_tensor)
        output_dense = output.dense()

        # Flatten the tensors for loss computation
        output_flat = output_dense.view(-1, output_dense.shape[1])
        labels_flat = labels_sparse_tensor.dense().view(-1).long()
        # labels_flat = labels_flat.unsqueeze(-1)
        loss = criterion(output_flat, labels_flat)
        loss.backward()
        optimizer.step()

        print(f"Epoch [{epoch + 1}/500], Loss: {loss.item()}")


    print('Output shape:', output.dense().shape)

    # Visualize label voxels
    # voxel_grid = visualize_labels_as_voxels(inputs.indices.cpu().numpy(), labels.cpu().numpy())
    # o3d.visualization.draw_geometries([voxel_grid])

    # Save a checkpoint
    # if (epoch + 1) % save_interval == 0 and epoch_val_loss < best_val_loss:
    #     best_val_loss = epoch_val_loss
    #     save_checkpoint(epoch + 1, model3d, optimizer, epoch_loss, checkpoint_dir,
    #                     filename=f'checkpoint_epoch_{epoch + 1}.pth.tar')

# print("Training complete")
# writer.close()
