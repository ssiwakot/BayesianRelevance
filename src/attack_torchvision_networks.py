from __future__ import division
from __future__ import print_function

from argparse import ArgumentParser
from utils.torchvision import *
from networks.torchvision.baseNN import *
from networks.torchvision.redBNN import *
from utils.data import load_from_pickle
from utils.seeding import *
from attacks.torchvision_attacks import *

parser = ArgumentParser()
parser.add_argument("--model", type=str, default="resnet", help="resnet, alexnet, vgg")
parser.add_argument("--dataset", type=str, default="animals10", 
                    help="imagenette, imagewoof, animals10, hymenoptera")
parser.add_argument("--debug", type=eval, default="False")
parser.add_argument("--train", type=eval, default="True")
parser.add_argument("--attack", type=eval, default="True")
parser.add_argument("--bayesian", type=eval, default="True")
parser.add_argument("--inference", type=str, default="svi", help="laplace, svi")
parser.add_argument("--samples", type=int, default=100, help="Number of posterior samples in the Bayesian case.")
parser.add_argument("--inputs", type=int, default=None, help="Number of input images. None loads all the available ones.")
parser.add_argument("--iters", type=int, default=5, help="Number of training iterations.")
parser.add_argument("--attack_method", type=str, default="fgsm", help="Attack name: fgsm, pgd.")
parser.add_argument("--device", type=str, default="cuda", help="cuda, cpu")
parser.add_argument("--savedir", type=str, default=None)
args = parser.parse_args()

print("PyTorch Version: ", torch.__version__)
print("Torchvision Version: ", torchvision.__version__)


################
# common setup #
################

batch_size = 128

if args.debug:
    savedir="debug"
    n_inputs=100
    iters=2
    n_samples=2

else:
    n_inputs=args.inputs
    iters=args.iters
    n_samples=args.samples

    if args.savedir:
        savedir = args.savedir 

    else:
        if args.bayesian:
            savedir = args.model+"_redBNN_"+args.dataset+"_"+args.inference+"_iters="+str(args.iters)
        else:
            savedir = args.model+"_baseNN_"+args.dataset+"_iters="+str(args.iters)


if args.device=="cuda":
    torch.set_default_tensor_type('torch.cuda.FloatTensor')

num_workers=0 if args.device=="cuda" else 4
device = torch.device(args.device)

dataloaders_dict, num_classes, im_idxs_dict = load_data(dataset_name=args.dataset, 
                                    batch_size=batch_size, n_inputs=n_inputs, num_workers=num_workers)

####################
# Train and attack #
####################

if args.bayesian:
    model = torchvisionBNN(model_name=args.model, dataset_name=args.dataset, inference=args.inference)
    model.initialize_model(model_name=args.model, num_classes=num_classes, 
                                                feature_extract=True, use_pretrained=True)
    model.to(device)

    if args.train:
        model.train(dataloaders_dict, num_iters=iters, device=device)
        model.save(savedir, iters)
    else:
        model.load(savedir, iters, device)

    if args.attack:
        adversarial_data = attack(network=model, dataloader=dataloaders_dict['test'], 
                     method=args.attack_method, n_samples=n_samples, device=device, savedir=savedir)
    else:
        adversarial_data = load_attack(method=args.attack_method, n_samples=n_samples, savedir=savedir)  
        if args.inputs:      
            adversarial_data = adversarial_data[im_random_idxs['test']]

    evaluate_attack(network=model, dataloader=dataloaders_dict['test'], adversarial_data=adversarial_data, 
                    n_samples=n_samples, device=device, method=args.attack_method, savedir=savedir)

else:

    model = torchvisionNN(model_name=args.model, dataset_name=args.dataset)
    params_to_update = model.initialize_model(model_name=args.model, num_classes=num_classes, 
                                                feature_extract=True, use_pretrained=True)
    model.to(device)

    if args.train:
        model.train(dataloaders_dict, params_to_update, num_iters=iters, device=device)
        model.save(savedir, iters)
    else:
        model.load(savedir, iters, device)

    if args.attack:
        adversarial_data = attack(network=model, dataloader=dataloaders_dict['test'], 
                    method=args.attack_method, device=device, savedir=savedir)
    else:
        adversarial_data = load_attack(method=args.attack_method, savedir=savedir)
        if args.inputs:      
            adversarial_data = adversarial_data[im_random_idxs['test']]

    evaluate_attack(network=model, dataloader=dataloaders_dict['test'], adversarial_data=adversarial_data, 
                    device=device, method=args.attack_method, savedir=savedir)

