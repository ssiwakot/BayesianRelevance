import os
from TorchLRP import lrp
import copy
import torch
import numpy as np
from torch import nn
from tqdm import tqdm
import torch.nn.functional as nnf
from torchvision import transforms
from scipy.stats import wasserstein_distance

from utils.savedir import *
from utils.seeding import set_seed
from utils.data import load_from_pickle, save_to_pickle

cmap_name="RdBu_r"
DEBUG=False


def select_informative_pixels(lrp_heatmaps, topk):
	"""
	Flattens image shape dimensions and selects the most relevant topk pixels. 
	Returns lrp heatmaps on the selected pixels and the chosen pixel indexes. 
	"""
	if DEBUG:
		print(f"\nTop {topk} most informative pixels:", end="\t")

	if len(lrp_heatmaps.shape)==3:
		if DEBUG:
			print(f"(image shape) = {lrp_heatmaps.shape}", end="\t")
		squeeze_dim=0

	elif len(lrp_heatmaps.shape)==4:
		if DEBUG:
			print(f"(n. images, image shape) = {lrp_heatmaps.shape[0], lrp_heatmaps.shape[1:]}")
		squeeze_dim=1

	elif len(lrp_heatmaps.shape)==5:
		if DEBUG:
			print(f"(samples_list_size, n. images, image shape) = {lrp_heatmaps.shape[0], lrp_heatmaps.shape[1], lrp_heatmaps.shape[2:]}")
		squeeze_dim=2

	else:
		raise ValueError("Wrong array shape.")

	flat_lrp_heatmaps = lrp_heatmaps.reshape(*lrp_heatmaps.shape[:squeeze_dim], -1)

	if len(flat_lrp_heatmaps.shape)==2:
		flat_lrp_heatmap = flat_lrp_heatmaps.sum(0)

	elif len(flat_lrp_heatmaps.shape)>2:
		flat_lrp_heatmap = flat_lrp_heatmaps.sum(0).sum(0)

	else:
		flat_lrp_heatmap = flat_lrp_heatmaps

	chosen_pxl_idxs = torch.argsort(flat_lrp_heatmap)[-topk:]
	chosen_pxls_lrp = flat_lrp_heatmaps[..., chosen_pxl_idxs] 

	if DEBUG:
		print("out shape =", chosen_pxls_lrp.shape)#, end="\t")
		# print("chosen pixels idxs =", chosen_pxl_idxs)

	return chosen_pxls_lrp, chosen_pxl_idxs


def compute_explanations(x_test, network, rule, method, n_samples=None, layer_idx=-1, avg_posterior=False):

	print("\nLRP layer idx =", layer_idx)

	layer_idx = network._set_correct_layer_idx(layer_idx)

	import itertools
	if hasattr(network, "basenet"):
		print(nn.Sequential(*list(network.basenet.model.children())[:layer_idx]))
	else:
		print(nn.Sequential(*list(network.model.children())[:layer_idx]))

	if n_samples is None or avg_posterior is True:

		explanations = []

		for x in tqdm(x_test):
			x = x.detach()
			x.requires_grad=True
			# Forward pass
			y_hat = network.forward(x.unsqueeze(0), explain=True, rule=rule, layer_idx=layer_idx,
									avg_posterior=avg_posterior)

			# Choose argmax
			y_hat = y_hat[torch.arange(x.shape[0]), y_hat.max(1)[1]].sum()

			# Backward pass (compute explanation)
			y_hat.backward()
			lrp = x.grad
			explanations.append(lrp)

	else:

		if method=="avg_prediction":

			explanations = []
			for x in tqdm(x_test):

				# Forward pass
				x_copy = copy.deepcopy(x.detach()).unsqueeze(0)
				x_copy.requires_grad = True	
				y_hat = network.forward(inputs=x_copy, n_samples=n_samples, explain=True, rule=rule, layer_idx=layer_idx)

				# Choose argmax
				y_hat = y_hat[torch.arange(x_copy.shape[0]), y_hat.max(1)[1]]
				y_hat = y_hat.sum()

				# Backward pass (compute explanation)
				y_hat.backward()
				lrp = x_copy.grad.squeeze(1)
				explanations.append(lrp)

		elif method=="avg_heatmap":

			explanations = []
			for x in tqdm(x_test):

				post_explanations = []
				for j in range(n_samples):

					# Forward pass
					x_copy = copy.deepcopy(x.detach()).unsqueeze(0)
					x_copy.requires_grad = True
					y_hat = network.forward(inputs=x_copy, n_samples=1, sample_idxs=[j], 
											explain=True, rule=rule, layer_idx=layer_idx)
					
					# Choose argmax
					y_hat = y_hat[torch.arange(x_copy.shape[0]), y_hat.max(1)[1]]
					y_hat = y_hat.sum()

					# Backward pass (compute explanation)
					y_hat.backward()
					lrp = x_copy.grad.squeeze(1)
					post_explanations.append(lrp)

				explanations.append(torch.stack(post_explanations).mean(0))

	explanations = torch.stack(explanations) 
	return explanations

def normalize(lrp):
	return 2*(lrp-lrp.min())/(lrp.max()-lrp.min())-1

def compute_vanishing_norm_idxs(inputs, n_samples_list, norm="linfty"):

	if inputs.shape[0] != len(n_samples_list):
		raise ValueError("First dimension should equal the length of `n_samples_list`")

	inputs=np.transpose(inputs, (1, 0, 2, 3, 4))
	vanishing_norm_idxs = []
	non_null_idxs = []

	print("\nvanishing norms:\n")
	count_van_images = 0
	count_incr_images = 0
	count_null_images = 0

	for idx, image in enumerate(inputs):

		if norm == "linfty":
			inputs_norm = np.max(np.abs(image[0]))
		elif norm == "l2":
			inputs_norm = np.linalg.norm(image[0])  
		else:
			raise ValueError("Wrong norm name")
		
		if inputs_norm != 0.0:
			if DEBUG:
				print("idx =",idx, end="\t")
			count_samples_idx = 0
			for samples_idx, n_samples in enumerate(n_samples_list):

				if norm == "linfty":
					new_inputs_norm = np.max(np.abs(image[samples_idx]))
				elif norm == "l2":
					new_inputs_norm = np.linalg.norm(image[samples_idx])

				if new_inputs_norm <= inputs_norm:
					if DEBUG:
						print(new_inputs_norm, end="\t")
					inputs_norm = copy.deepcopy(new_inputs_norm)
					count_samples_idx += 1

			if count_samples_idx == len(n_samples_list):
				vanishing_norm_idxs.append(idx)
				non_null_idxs.append(idx)
				if DEBUG:
					print("\tcount=", count_van_images)
				count_van_images += 1
			else: 
				non_null_idxs.append(idx)
				count_incr_images += 1

			if DEBUG:
				print("\n")

		else:
			count_null_images += 1

	print(f"vanishing norms = {100*count_van_images/len(inputs)} %")
	print(f"increasing norms = {100*count_incr_images/len(inputs)} %")
	print(f"null norms = {100*count_null_images/len(inputs)} %")
	print("\nvanishing norms idxs = ", vanishing_norm_idxs)
	return vanishing_norm_idxs, non_null_idxs

def lrp_distances(original_heatmaps, adversarial_heatmaps, pxl_idxs=None, axis_norm=0):

	if original_heatmaps.shape[0]==0:
		return torch.empty(0)

	original_heatmaps = original_heatmaps.reshape(*original_heatmaps.shape[:1], -1)
	adversarial_heatmaps = adversarial_heatmaps.reshape(*adversarial_heatmaps.shape[:1], -1)

	if pxl_idxs is not None:
		original_heatmaps = original_heatmaps[:, pxl_idxs]
		adversarial_heatmaps = adversarial_heatmaps[:, pxl_idxs]

	distances = torch.norm(original_heatmaps-adversarial_heatmaps, dim=axis_norm)
	return distances

def lrp_robustness(original_heatmaps, adversarial_heatmaps, topk, method):
	"""
	Point-wise robustness measure. Computes the fraction of common topk relevant pixels between each original
	image and adversarial image.
	"""

	robustness = []
	chosen_pxl_idxs=[]

	# print(original_heatmaps.shape, adversarial_heatmaps.shape)

	if method=="imagewise":

		for im_idx in range(len(original_heatmaps)):
			orig_pxl_idxs = select_informative_pixels(original_heatmaps[im_idx], topk=topk)[1]
			adv_pxl_idxs = select_informative_pixels(adversarial_heatmaps[im_idx], topk=topk)[1]

			pxl_idxs = np.intersect1d(orig_pxl_idxs.detach().cpu().numpy(), adv_pxl_idxs.detach().cpu().numpy())

			robustness.append(len(pxl_idxs)/topk)
			chosen_pxl_idxs.append(pxl_idxs)

	elif method=="pixelwise":

		for im_idx in range(len(original_heatmaps)):
			orig_pxl_idxs = select_informative_pixels(original_heatmaps[im_idx], topk=topk)[1]
			adv_pxl_idxs = select_informative_pixels(adversarial_heatmaps[im_idx], topk=topk)[1]
			pxl_idxs = np.intersect1d(orig_pxl_idxs.detach().cpu().numpy(), adv_pxl_idxs.detach().cpu().numpy())
			chosen_pxl_idxs.extend(pxl_idxs)

		distances = lrp_distances(original_heatmaps, adversarial_heatmaps, chosen_pxl_idxs)
		robustness = -np.array(distances.detach().cpu().numpy())

	else:
		raise NotImplementedError

	if DEBUG:
		print("\n", pxl_idxs.shape, np.array(chosen_pxl_idxs).shape, np.array(robustness).shape)

	return np.array(robustness), np.array(chosen_pxl_idxs)

