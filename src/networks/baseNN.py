"""
Deterministic Neural Network model.
Last layer is separated from the others.
"""

import os
import argparse
import numpy as np
import torch
from torch import nn
import torch.nn.functional as nnf
import torch.optim as torchopt
import torch.nn.functional as F

from utils.data import *
from utils.savedir import *
from utils.seeding import *
from utils.model_settings import baseNN_settings

from TorchLRP import lrp

DEBUG = False


class baseNN(nn.Module):

    def __init__(self, input_shape, output_size, dataset_name, hidden_size, activation, 
                       architecture, epochs, lr):
        super(baseNN, self).__init__()

        if math.log(hidden_size, 2).is_integer() is False or hidden_size<16:
            raise ValueError("\nhidden size should be a power of 2 greater than 16.")

        self.dataset_name = dataset_name
        self.architecture = architecture
        self.hidden_size = hidden_size 
        self.activation = activation
        self.lr, self.epochs = lr, epochs
        self.loss_func = nn.CrossEntropyLoss()
        self.set_model(architecture, activation, input_shape, output_size, hidden_size)
        self.name = str(dataset_name)+"_baseNN_hid="+str(hidden_size)+\
                    "_arch="+str(self.architecture)+"_act="+str(self.activation)+\
                    "_ep="+str(self.epochs)+"_lr="+str(self.lr)

        print("\nbaseNN total number of weights =", sum(p.numel() for p in self.parameters()))
        self.n_layers = len(list(self.model.children()))
        learnable_params = self.model.state_dict()
        self.n_learnable_layers = int(len(learnable_params)/2)

    def set_model(self, architecture, activation, input_shape, output_size, hidden_size):

        input_size = input_shape[0]*input_shape[1]*input_shape[2]
        in_channels = input_shape[0]

        if activation == "relu":
            activ = nn.ReLU
        elif activation == "leaky":
            activ = nn.LeakyReLU
        elif activation == "sigm":
            activ = nn.Sigmoid
        elif activation == "tanh":
            activ = nn.Tanh
        else: 
            raise AssertionError("\nWrong activation name.")

        if architecture == "fc":

            self.model = nn.Sequential(
                nn.Flatten(), 
                lrp.Linear(input_size, hidden_size),
                activ(),
                lrp.Linear(hidden_size, output_size))

            self.learnable_layers_idxs = [1, 3]

        elif architecture == "fc2":
            self.model = nn.Sequential(
                nn.Flatten(),
                lrp.Linear(input_size, hidden_size),
                activ(),
                lrp.Linear(hidden_size, hidden_size),
                activ(),
                lrp.Linear(hidden_size, output_size)
                )

            self.learnable_layers_idxs = [1, 3, 5]

        elif architecture == "fc4":
            self.model = nn.Sequential(
                nn.Flatten(),
                lrp.Linear(input_size, hidden_size),
                activ(),
                lrp.Linear(hidden_size, hidden_size),
                activ(),
                lrp.Linear(hidden_size, hidden_size),
                activ(),
                lrp.Linear(hidden_size, hidden_size),
                activ(),
                lrp.Linear(hidden_size, output_size))

            self.learnable_layers_idxs = [1, 3, 5, 7, 9]

        elif architecture == "conv":

            if self.dataset_name in ["mnist","fashion_mnist"]:

                self.model = nn.Sequential(
                    lrp.Conv2d(in_channels, 16, kernel_size=5),
                    activ(),
                    nn.MaxPool2d(kernel_size=2),
                    lrp.Conv2d(16, hidden_size, kernel_size=5),
                    activ(),
                    nn.MaxPool2d(kernel_size=2, stride=1),
                    nn.Flatten(),
                    lrp.Linear(int(hidden_size/(4*4))*input_size, output_size))

                self.learnable_layers_idxs = [0, 3, 7]

            else:
                raise NotImplementedError()

        else:
            raise NotImplementedError()

    def train(self, train_loader, savedir, device):
        print("\n == baseNN training ==")
        self.to(device)

        optimizer = torchopt.Adam(params=self.parameters(), lr=self.lr)

        start = time.time()
        for epoch in range(self.epochs):
            total_loss = 0.0
            correct_predictions = 0.0

            for x_batch, y_batch in train_loader:

                x_batch = x_batch.to(device)
                y_batch = y_batch.to(device).argmax(-1)
                outputs = self.forward(x_batch)
                
                optimizer.zero_grad()
                loss = self.loss_func(outputs, y_batch)
                loss.backward()
                optimizer.step()

                predictions = outputs.argmax(dim=1)
                correct_predictions += (predictions == y_batch).sum()
                total_loss += loss.data.item() / len(train_loader.dataset)
            
            accuracy = 100 * correct_predictions / len(train_loader.dataset)
            print(f"\n[Epoch {epoch + 1}]\t loss: {total_loss:.8f} \t accuracy: {accuracy:.2f}", 
                  end="\t")

        execution_time(start=start, end=time.time())
        self.save(savedir)

    def _get_learnable_layer_idx(self, layer_idx):

        if abs(layer_idx)>self.n_layers:
            raise ValueError(f"Max number of available layers is {self.n_layers}")

        if layer_idx<0:
            layer_idx = self.learnable_layers_idxs[layer_idx]
        else:
            layer_idx = self.learnable_layers_idxs[layer_idx]

        return layer_idx

    def _set_correct_layer_idx(self, layer_idx):

        """
        -1 = n_learnable_layers-1 = last learnable layer idx
        0 = -n_learnable_layers = firsy learnable layer idx  
        """
        # if layer_idx is not None:
        if abs(layer_idx)>self.n_layers:
            raise ValueError(f"Max number of available layers is {self.n_layers}")

        if layer_idx==-1:
            layer_idx=None
        else:
            if layer_idx<0:
                layer_idx+=self.n_layers+1
            else:
                layer_idx+=1

        return layer_idx

    def forward(self, inputs, layer_idx=-1, softmax=False, *args, **kwargs):

        layer_idx = self._set_correct_layer_idx(layer_idx)

        # preds = nn.Sequential(*list(self.model.children())[:layer_idx])(inputs)

        model = lrp.Sequential(*list(self.model.children())[:layer_idx])
        preds = model.forward(inputs, *args, **kwargs)

        if softmax:
            preds = nnf.softmax(preds, dim=-1)

        return preds

    def get_logits(self, *args, **kwargs):
        return self.forward(layer_idx=-1, *args, **kwargs)

    def save(self, savedir):

        filename=self.name+"_weights.pt"
        os.makedirs(savedir, exist_ok=True)

        self.to("cpu")
        torch.save(self.state_dict(), os.path.join(savedir, filename))

        if DEBUG:
            print("\nCheck saved weights:")
            print("\nstate_dict()['l2.0.weight'] =", self.state_dict()["l2.0.weight"][0,0,:3])
            print("\nstate_dict()['out.weight'] =",self.state_dict()["out.weight"][0,:3])

    def load(self, device, savedir):

        filename=self.name+"_weights.pt"

        self.load_state_dict(torch.load(os.path.join(savedir, filename)))
        self.to(device)

        if DEBUG:
            print("\nCheck loaded weights:")    
            print("\nstate_dict()['l2.0.weight'] =", self.state_dict()["l2.0.weight"][0,0,:3])
            print("\nstate_dict()['out.weight'] =",self.state_dict()["out.weight"][0,:3])

    def evaluate(self, test_loader, device, *args, **kwargs):
        self.to(device)

        with torch.no_grad():
            correct_predictions = 0.0

            for x_batch, y_batch in test_loader:
                x_batch = x_batch.to(device)
                y_batch = y_batch.to(device).argmax(-1)
                outputs = self(x_batch)
                predictions = outputs.argmax(dim=1)
                correct_predictions += (predictions == y_batch).sum()

            accuracy = 100 * correct_predictions / len(test_loader.dataset)
            print("\nAccuracy: %.2f%%" % (accuracy))
            return accuracy
