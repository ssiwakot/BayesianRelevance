import os
import lrp
import copy
import torch
import numpy as np
from tqdm import tqdm
import matplotlib
import pandas as pd
import seaborn as sns
import matplotlib.colors as colors 
import matplotlib.pyplot as plt
from matplotlib.pyplot import cm

from utils.savedir import *
from utils.seeding import set_seed
from utils.lrp import *

relevance_cmap = "RdBu_r"

def plot_explanations(images, explanations, rule, savedir, filename, layer_idx=-1):

    savedir = os.path.join(savedir, lrp_savedir(layer_idx))

    if images.shape != explanations.shape:
        print(images.shape, "!=", explanations.shape)
        raise ValueError

    cmap = plt.cm.get_cmap(relevance_cmap)

    rows = 2
    cols = min(len(explanations), 6)
    fig, axes = plt.subplots(rows, cols, figsize=(12, 4))
    fig.tight_layout()

    set_seed(0)
    idxs = np.random.choice(len(explanations), cols)

    for idx, col in enumerate(range(cols)):

        image = np.squeeze(images[idx])
        expl = np.squeeze(explanations[idx])

        if len(image.shape) == 1:
            image = np.expand_dims(image, axis=0)
            expl = np.expand_dims(expl, axis=0)

        axes[0, col].imshow(image)
        im = axes[1, col].imshow(expl, cmap=cmap)

    os.makedirs(savedir, exist_ok=True)
    plt.savefig(os.path.join(savedir,filename+".png"))

def relevant_subset(images, pxl_idxs):

    flat_images = images.reshape(*images.shape[:2], -1)
    images_rel = np.zeros(flat_images.shape)

    for image_idx, pxl_idx in enumerate(pxl_idxs):
        images_rel[image_idx,:,pxl_idx] = flat_images[image_idx,:,pxl_idx]
    
    images_rel = images_rel.reshape(images.shape)
    return images_rel

def plot_attacks_explanations(images, explanations, attacks, attacks_explanations, 
                              predictions, attacks_predictions, labels,
                              pxl_idxs, rule, savedir, filename, layer_idx=-1):

    images_cmap='Greys'

    set_seed(0)
    idxs = np.random.choice(len(images), 6)
    images = images[idxs].detach().cpu().numpy()
    explanations = explanations[idxs].detach().cpu().numpy()
    attacks = attacks[idxs].detach().cpu().numpy()
    attacks_explanations = attacks_explanations[idxs].detach().cpu().numpy()
    predictions = predictions[idxs].detach().cpu().numpy()
    attacks_predictions = attacks_predictions[idxs].detach().cpu().numpy()
    labels = labels[idxs].detach().cpu().numpy()

    if images.shape != explanations.shape:
        print(images.shape, "!=", explanations.shape)
        raise ValueError

    images_rel = relevant_subset(images, pxl_idxs[idxs])
    images_rel = np.ma.masked_where(images_rel == 0., images_rel)
    attacks_rel = relevant_subset(attacks, pxl_idxs[idxs])
    attacks_rel = np.ma.masked_where(attacks_rel == 0., attacks_rel)
    explanations = relevant_subset(explanations, pxl_idxs[idxs])
    attacks_explanations = relevant_subset(attacks_explanations, pxl_idxs[idxs])

    cmap = plt.cm.get_cmap(relevance_cmap)

    vmax_expl = max([max(explanations.flatten()), 0.000001])
    vmin_expl = min([min(explanations.flatten()), -0.000001])
    norm_expl = colors.TwoSlopeNorm(vcenter=0., vmax=vmax_expl, vmin=vmin_expl)

    vmax_atk_expl = max([max(attacks_explanations.flatten()), 0.000001])
    vmin_atk_expl = min([min(attacks_explanations.flatten()), -0.000001])
    norm_atk_expl = colors.TwoSlopeNorm(vcenter=0., vmax=vmax_atk_expl, vmin=vmin_atk_expl)

    rows = 4
    cols = min(len(explanations), 6)
    fig, axes = plt.subplots(rows, cols, figsize=(8, 6), dpi=150)
    fig.tight_layout()

    for idx in range(cols):

        image = np.squeeze(images[idx])
        image_rel = np.squeeze(images_rel[idx])
        expl = np.squeeze(explanations[idx])
        attack = np.squeeze(attacks[idx])
        attack_rel = np.squeeze(attacks_rel[idx])
        attack_expl = np.squeeze(attacks_explanations[idx])

        if len(image.shape) == 1:
            image = np.expand_dims(image, axis=0)
            image_rel = np.expand_dims(image_rel, axis=0)
            expl = np.expand_dims(expl, axis=0)
            attack = np.expand_dims(attack, axis=0)
            attack_rel = np.expand_dims(attack_rel, axis=0)
            attack_expl = np.expand_dims(attack_expl, axis=0)

        axes[0, idx].imshow(image, cmap=images_cmap)
        axes[0, idx].imshow(image_rel)
        axes[0, idx].set_xlabel(f"label={labels[idx]}\nprediction={predictions[idx]}")
        expl = axes[1, idx].imshow(expl, cmap=cmap, norm=norm_expl)
        axes[2, idx].imshow(attack, cmap=images_cmap)
        axes[2, idx].imshow(attack_rel)
        axes[2, idx].set_xlabel(f"prediction={attacks_predictions[idx]}")
        atk_expl = axes[3, idx].imshow(attack_expl, cmap=cmap, norm=norm_atk_expl)

        axes[0,0].set_ylabel("images")
        axes[1,0].set_ylabel("lrp(images)")
        axes[2,0].set_ylabel("im. attacks")
        axes[3,0].set_ylabel("lrp(attacks)")

    fig.subplots_adjust(right=0.85)

    cbar_ax = fig.add_axes([0.9, 0.57, 0.01, 0.15])
    cbar = fig.colorbar(expl, ax=axes[0, :].ravel().tolist(), cax=cbar_ax)
    cbar.set_label('Relevance', labelpad=-70)

    cbar_ax = fig.add_axes([0.9, 0.08, 0.01, 0.15])
    cbar = fig.colorbar(atk_expl, ax=axes[2, :].ravel().tolist(), cax=cbar_ax)
    cbar.set_label('Relevance', labelpad=-60)

    os.makedirs(savedir, exist_ok=True)
    plt.savefig(os.path.join(savedir,filename+".png"))

def plot_vanishing_explanations(images, samples_explanations, n_samples_list, rule, savedir, filename,
                                layer_idx=-1):
    
    savedir = os.path.join(savedir, lrp_savedir(layer_idx))

    if images.shape != samples_explanations[0].shape:
        print(images.shape, "!=", samples_explanations[0].shape)
        raise ValueError

    vanishing_idxs=compute_vanishing_norm_idxs(samples_explanations, n_samples_list, norm="linfty")[0]   

    if len(vanishing_idxs)<=1:
        raise ValueError("Not enough examples.")

    rows = min(len(n_samples_list), 5)+1
    cols = min(len(vanishing_idxs), 6)

    set_seed(0)
    chosen_idxs = np.random.choice(vanishing_idxs, cols)

    fig, axes = plt.subplots(rows, cols, figsize=(10, 6))
    fig.tight_layout()

    for col_idx in range(cols):

        cmap = plt.cm.get_cmap(relevance_cmap)
        vmax = max(samples_explanations[:, chosen_idxs[col_idx]].flatten())
        vmin = min(samples_explanations[:, chosen_idxs[col_idx]].flatten())
        norm = colors.TwoSlopeNorm(vcenter=0., vmax=vmax, vmin=vmin)

        for samples_idx, n_samples in enumerate(n_samples_list):

            image = np.squeeze(images[chosen_idxs[col_idx]])
            image = np.expand_dims(image, axis=0) if len(image.shape) == 1 else image

            expl = np.squeeze(samples_explanations[samples_idx, chosen_idxs[col_idx]])
            expl = np.expand_dims(expl, axis=0) if len(expl.shape) == 1 else expl

            axes[0, col_idx].imshow(image)
            im = axes[samples_idx+1, col_idx].imshow(expl, cmap=cmap, norm=norm)

        # fig.subplots_adjust(right=0.83)
        # cbar_ax = fig.add_axes([0.88, 0.12, 0.02, 0.6])
        # cbar = fig.colorbar(im, ax=axes[samples_idx+1, :].ravel().tolist(), cax=cbar_ax)
        # cbar.set_label('Relevance', labelpad=10)

    os.makedirs(savedir, exist_ok=True)
    plt.savefig(os.path.join(savedir, filename+".png"))