# coding: utf-8

import torch
import torch.nn as nn
import torch.nn.functional as F
from caps import CapsuleLayer
import numpy as np


def initialize_weights(module):
    if isinstance(module, nn.Conv2d):
        nn.init.kaiming_normal_(module.weight.data, mode='fan_out')
    elif isinstance(module, nn.BatchNorm2d):
        nn.init.constant_(module.weight, 1)
        nn.init.constant_(module.bias, 0)
    elif isinstance(module, nn.Linear):
        nn.init.constant_(module.bias, 0)


class BasicBlock(nn.Module):
    def __init__(self, in_channels, out_channels, stride):
        super(BasicBlock, self).__init__()

        self.bn1 = nn.BatchNorm2d(in_channels)
        self.conv1 = nn.Conv2d(
            in_channels,
            out_channels,
            kernel_size=3,
            stride=stride,
            padding=1,
            bias=False)
        self.bn2 = nn.BatchNorm2d(out_channels)
        self.conv2 = nn.Conv2d(
            out_channels,
            out_channels,
            kernel_size=3,
            stride=1,
            padding=1,
            bias=False)

        self.shortcut = nn.Sequential()
        if in_channels != out_channels:
            self.shortcut.add_module(
                'conv',
                nn.Conv2d(
                    in_channels,
                    out_channels,
                    kernel_size=1,
                    stride=stride,
                    padding=0,
                    bias=False))

    def forward(self, x):
        x = F.relu(self.bn1(x), inplace=True)
        y = self.conv1(x)
        y = F.relu(self.bn2(y), inplace=True)
        y = self.conv2(y)
        y += self.shortcut(x)
        return y


class Model(nn.Module):
    def __init__(self):
        super(Model, self).__init__()

        depth = 8
        base_channels = 16
        input_shape = (1, 3, 36, 60)

        n_blocks_per_stage = (depth - 2) // 6
        assert n_blocks_per_stage * 6 + 2 == depth

        n_channels = [base_channels, base_channels * 2, base_channels * 4]

        self.conv = nn.Conv2d(
            input_shape[1],
            n_channels[0],
            kernel_size=(3, 3),
            stride=1,
            padding=1,
            bias=False)

        self.stage1 = self._make_stage(
            n_channels[0],
            n_channels[0],
            n_blocks_per_stage,
            BasicBlock,
            stride=1)
        self.stage2 = self._make_stage(
            n_channels[0],
            n_channels[1],
            n_blocks_per_stage,
            BasicBlock,
            stride=2)
        self.stage3 = self._make_stage(
            n_channels[1],
            n_channels[2],
            n_blocks_per_stage,
            BasicBlock,
            stride=2)
        self.bn = nn.BatchNorm2d(n_channels[2])

        self.primary_capsules = CapsuleLayer(num_capsules=4, num_route_nodes=-1, in_channels=64, out_channels=4, kernel_size=5, stride=1)
        self.digit_capsules = CapsuleLayer(num_capsules=4, num_route_nodes=4 * 4 * 7, in_channels=4, out_channels=4)
        self.conv4 = nn.Conv2d(64, 1, kernel_size=3, stride=1, padding=1)  # 若卷积核大小为3x3, 那么就应该设定padding=1, 即填充1层边缘像素; 若卷积核大小为7x7, 那么就应该设定padding=3
        # num_capsules=8 数字胶囊的个数; num_route_nodes: 一个立方体的体积; in_channels=4 初始胶囊立方体个数; out_channels=4 数字胶囊的长度

        self.fc1 = nn.Linear(64 + 0, 62) # num_capsules * out_channels
        self.fc2 = nn.Linear(64, 2)
        self.avg = nn.AdaptiveAvgPool2d(1)
        self.apply(initialize_weights)

    def _initialize_weight(self):
        nn.init.normal_(self.conv4.weight, mean=0, std=0.01) # added by JZ Chen
        self.apply(initialize_weights)

    def _make_stage(self, in_channels, out_channels, n_blocks, block, stride):
        stage = nn.Sequential()
        for index in range(n_blocks):
            block_name = 'block{}'.format(index + 1)
            if index == 0:
                stage.add_module(
                    block_name, block(in_channels, out_channels, stride=stride))
            else:
                stage.add_module(block_name, block(out_channels, out_channels, stride=1))
        return stage

    def _forward_conv(self, x):
        x = self.conv(x)
        x = self.stage1(x)
        x = self.stage2(x)
        x = self.stage3(x)
        x = F.relu(self.bn(x), inplace=True)
        # x = F.adaptive_avg_pool2d(x, output_size=1)
        return x

    def forward(self, x, y):
        print(x.shape)
        print(y.shape)
        x = self._forward_conv(x)  #(64,64,9,15)
        h = x.shape[2]
        w = x.shape[3]
        d = 64
        d2=int(d*(d+1)/2)
        # self.conctod = nn.Conv2d(64, d, kernel_size=1)
        # x=self.conctod(x)
        x=x.permute(0,2,3,1)  #(64,9,15,64)
        Y1=x.unsqueeze(3)  #(64,9,15,1,64)
        Y2=x.unsqueeze(4)  #(64,9,15,64,1)

        Y=Y1.mul(Y2)  #torch.Size([64, 9, 15, 64, 64])
        #Y=Y.cpu().numpy()
        #Y=Y.reshape(64,135,64,64)
        #z = np.ones((64,135, d2))
        z = torch.ones((64, 9,15, d2))
        k = 0
        for row in range(d):
            for col in range(row,d):
                z[...,k]=Y[...,row,col]
                k = k + 1
                if(col==row==d-1):k=0
        z = z.permute(0, 3, 1, 2)
        self.condtoc = nn.Conv2d(d2, 64, kernel_size=1)
        A = self.condtoc(z)  # torch.Size([64, 64, 9, 15])
        G = self.avg(A)
        D = torch.mul(A, G) + A
        x = torch.mul(x, D) + x
        print(x.shape)  ### x is P on the figure

        # self.condtoc = nn.Conv2d(d2, 64, kernel_size=1)
        # A=self.condtoc(z)   #torch.Size([64, 64, 9, 15])
        # A = A.permute(0, 2, 3, 1)
        # A1 = A.unsqueeze(3)  #torch.Size([64, 9, 15, 1, 64])
        # A2 = A.unsqueeze(4)  #torch.Size([64, 9, 15, 64, 1])
        # G=(A1.mul(A2))/(h*w) #torch.Size([64, 9, 15, 64, 64])
        # print(G.shape())
        # U=torch.ones((64, 9, 15, 64, 64))
        # D=(U+G)*A

        # x1=x.cpu().reshape((64,135,64)) #(64,64,135)
        # y1=x1.numpy()               #(64,64,135)
        # y2 = np.ones((64, 135, 64)) #(64,135,64)
        # y3=np.ones((64,64,64))
        # d=64
        # d2=d*(d+1)/2
        # d2=int(d2)
        # for i in range(64):
        #     y2[i] = np.transpose(y1[i])
        #     y3[i]=np.matmul(y1[i],y2[i])
        # tri=(np.triu(y3,k=0))
        # z=np.ones((64,d2))
        # k=0
        # for bs in range(64):
        #     for row in range(d):
        #         for col in range(row,d):
        #             z[bs][k]=tri[bs][row][col]
        #             k=k+1
        #             if(col==row==d-1):k=0
        # #print(z.shape)
        # z=z.reshape(64,d2,h,w)
        # z.torch.tensor(z)
        # #print(type(z))



    # # attention, added by JZ Chen
    #     x = F.max_pool2d(x, kernel_size=2, stride=2)
    #     z = self.conv4(x)
    #     z = F.sigmoid(z)
    #     z = z.repeat(1, 64, 1, 1)
    #     z = torch.mul(x, z)
    #     x = torch.add(z, x)
    # # attention
    # CapsNet
    #     x = F.max_pool2d(x, kernel_size=2, stride=2)
    #     c = self.primary_capsules(x)
    #     c = self.digit_capsules(c)
    #     c = c.squeeze(2).squeeze(2).transpose(0, 1)
    #     c = c.reshape(c.size(0), -1)
    #     x = x.reshape(x.size(0), -1)
    #     x = torch.cat([x, c], dim=1)
    # CapsNet
    #     x = F.adaptive_avg_pool2d(x, output_size=1)
    #     x = F.relu(self.fc1(x.view(x.size(0), -1)), inplace=True)
    #     # print(x.shape)
    #     x = torch.cat([x, y], dim=1)  # concated with pose
    #     x = self.fc2(x)
        return x