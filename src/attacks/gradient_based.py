"""
FGSM and PGD classic & bayesian adversarial attacks 
"""

import sys
import argparse
from tqdm import tqdm
import pyro
import random
import copy
import torch
import numpy as np
from torch.utils.data import DataLoader
import torch.nn.functional as nnf
import pandas
import os

from utils.savedir import *
from utils.data import *
from utils.networks import *
from attacks.robustness_measures import *
from attacks.plot import plot_grid_attacks


DEBUG=False

def loss_gradient_sign(net, n_samples, image, label):

    if n_samples is None:

        image.requires_grad = True
        output = net.forward(inputs=image, expected_out=False)
        
        loss = torch.nn.CrossEntropyLoss()(output, label)
        net.zero_grad()
        loss.backward()
        gradient_sign = image.grad.data.sign()

    else:

        loss_gradients=[]

        for i in range(n_samples):

            x_copy = copy.deepcopy(image)
            x_copy.requires_grad = True
            output = net.forward(inputs=x_copy, n_samples=1, sample_idxs=[i])#, exp=True)[0]

            loss = torch.nn.CrossEntropyLoss()(output.to(dtype=torch.double), label)
            net.zero_grad()
            loss.backward()
            loss_gradient = copy.deepcopy(x_copy.grad.data[0].sign())
            loss_gradients.append(loss_gradient)

        # gradient_sign = torch.stack(loss_gradients,0).sign().mean(0)
        gradient_sign = torch.stack(loss_gradients,0).mean(0)

    return gradient_sign


def fgsm_attack(net, image, label, hyperparams=None, n_samples=None, avg_posterior=False):

    epsilon = hyperparams["epsilon"] if hyperparams is not None else 0.25
    
    gradient_sign = loss_gradient_sign(net, n_samples, image, label)
    perturbed_image = image + epsilon * gradient_sign
    perturbed_image = torch.clamp(perturbed_image, 0, 1)
    return perturbed_image


def pgd_attack(net, image, label, hyperparams=None, n_samples=None, avg_posterior=False):

    if hyperparams is not None: 
        epsilon, alpha, iters = (hyperparams["epsilon"], 2/image.max(), 40)
    else:
        epsilon, alpha, iters = (0.25, 2/225, 40)

    original_image = copy.deepcopy(image)
    
    for i in range(iters):

        gradient_sign = loss_gradient_sign(net, n_samples, image, label)
        perturbed_image = image + alpha * gradient_sign
        eta = torch.clamp(perturbed_image - original_image, min=-epsilon, max=epsilon)
        image = torch.clamp(original_image + eta, min=0, max=1)

    perturbed_image = image.detach()
    return perturbed_image

def attack(net, x_test, y_test, device, method, filename, savedir,
           hyperparams=None, n_samples=None, avg_posterior=False):

    print(f"\n\nProducing {method} attacks", end="\t")
    if n_samples:
        print(f"with {n_samples} attack samples")

    net.to(device)
    x_test, y_test = x_test.to(device), y_test.to(device)

    adversarial_attack = []

    for idx in tqdm(range(len(x_test))):
        image = x_test[idx].unsqueeze(0)
        label = y_test[idx].argmax(-1).unsqueeze(0)

        if method == "fgsm":
            perturbed_image = fgsm_attack(net=net, image=image, label=label, 
                                          hyperparams=hyperparams, n_samples=n_samples,
                                          avg_posterior=avg_posterior)
        elif method == "pgd":
            perturbed_image = pgd_attack(net=net, image=image, label=label, 
                                          hyperparams=hyperparams, n_samples=n_samples,
                                          avg_posterior=avg_posterior)

        adversarial_attack.append(perturbed_image)

    adversarial_attack = torch.cat(adversarial_attack)

    name = filename+"_"+str(method)
    name = name+"_attackSamp="+str(n_samples)+"_attack" if n_samples else name+"_attack"

    savedir = os.path.join(path, ATK_DIR)
    save_to_pickle(data=adversarial_attack, path=savedir, filename=name)

    idxs = np.random.choice(len(x_test), 10, replace=False)
    original_images_plot = torch.stack([x_test[i].squeeze() for i in idxs])
    perturbed_images_plot = torch.stack([adversarial_attack[i].squeeze() for i in idxs])
    plot_grid_attacks(original_images=original_images_plot.detach().cpu(), 
                      perturbed_images=perturbed_images_plot.detach().cpu(), 
                      filename=name, savedir=savedir)

    return adversarial_attack

def load_attack(method, filename, savedir, n_samples=None):
    savedir = os.path.join(path, ATK_DIR)
    name = filename+"_"+str(method)
    name = name+"_attackSamp="+str(n_samples)+"_attack" if n_samples else name+"_attack"
    return load_from_pickle(path=savedir, filename=name)

def attack_evaluation(net, x_test, x_attack, y_test, device, n_samples=None):

    print(f"\nEvaluating against the attacks", end="")
    if n_samples:
        print(f" with {n_samples} defence samples")

    random.seed(0)
    pyro.set_rng_seed(0)
    
    x_test, x_attack, y_test = x_test.to(device), x_attack.to(device), y_test.to(device)

    if hasattr(net, 'net'):
        net.basenet.to(device) # fixed layers in BNN

    test_loader = DataLoader(dataset=list(zip(x_test, y_test)), batch_size=128, shuffle=False)
    attack_loader = DataLoader(dataset=list(zip(x_attack, y_test)), batch_size=128, shuffle=False)

    with torch.no_grad():

        original_outputs = []
        original_correct = 0.0
        for images, labels in test_loader:
            out = net.forward(images, n_samples)
            original_correct += ((out.argmax(-1) == labels.argmax(-1)).sum().item())
            original_outputs.append(out)

        adversarial_outputs = []
        adversarial_correct = 0.0
        for attacks, labels in attack_loader:
            out = net.forward(attacks, n_samples)
            adversarial_correct += ((out.argmax(-1) == labels.argmax(-1)).sum().item())
            adversarial_outputs.append(out)

        original_accuracy = 100 * original_correct / len(x_test)
        adversarial_accuracy = 100 * adversarial_correct / len(x_test)
        print(f"\ntest accuracy = {original_accuracy}\tadversarial accuracy = {adversarial_accuracy}",
              end="\t")

        original_outputs = torch.cat(original_outputs)
        adversarial_outputs = torch.cat(adversarial_outputs)
        softmax_rob = softmax_robustness(original_outputs, adversarial_outputs)

    return original_accuracy, adversarial_accuracy, softmax_rob
