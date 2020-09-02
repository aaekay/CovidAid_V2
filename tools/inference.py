"""
Script to process set of images and output predictions
"""
from RISE.visualize import visualize
import torch
from torch.utils.data import Dataset
from torch.utils.data import DataLoader
import torchvision.transforms as transforms
import torch.nn as nn
from PIL import Image
import os
import glob
import argparse
from model_AGCNN import CovidAidAttend
# from covidaid_v2 import CovidAID
from read_data_v3 import ChestXrayDataSetTest
from tqdm import tqdm
# import termtables as tt
from pprint import pprint
import numpy as np

# TEST_LIST="./data/aiimsClinical.txt"

USE_GPU=torch.cuda.is_available()
D_COUNT=1
use_List=False

def pred_converter(pred):
    new_pred=[]
    for i,arr in enumerate(pred):
        nonCovid = np.max(arr[:-1])
        covid = arr[-1]
        temp = np.array([nonCovid,covid])
        new_pred.append(temp)
    return np.stack(new_pred)


class CovidDataLoader(Dataset):
    """
    Read images and corresponding labels.
    """
    def __init__(self, image_dir, transform=None):
        """
        Args:
            image_dir: path to image directory.
            transform: optional transform to be applied on a sample.
        """
        self.image_names = [img for img in glob.glob(os.path.join(image_dir, '**/*.jpg'),recursive=True)]
        self.transform = transform

    def __getitem__(self, index):
        """
        Args:
            index: the index of item

        Returns:
            image and its name
        """
        image_name = self.image_names[index]
        image = Image.open(image_name).convert('RGB')
        if self.transform is not None:
            image = self.transform(image)
        return image, image_name.split('/')[-1]

    def __len__(self):
        return len(self.image_names)



if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--img_dir", type=str, required=True)
    parser.add_argument("--checkpoint", type=str, default="models/Global_Best.pth")
    parser.add_argument("--combine_pneumonia", action='store_true', default=False)
    parser.add_argument("--visualize_dir", type=str, default=None)
    parser.add_argument("--binary_eval", action='store_true', default=False)

    args = parser.parse_args()

    # Load the model
    model = CovidAidAttend(args.combine_pneumonia)
    model.load_state_dict(torch.load(args.checkpoint, map_location={'cuda:0':'cpu'}))
    
    if D_COUNT>1:
        print("Using", torch.cuda.device_count(), "GPUs!")
        model=nn.DataParallel(model)

    if USE_GPU:
        model.cuda()
        
    
    
    # Load the data
    normalize = transforms.Normalize([0.485, 0.456, 0.406],
                                     [0.229, 0.224, 0.225])
    
    if not use_List:
        test_dataset = CovidDataLoader(image_dir=args.img_dir,
                transform=transforms.Compose([
                    transforms.Resize(256),
                    transforms.TenCrop(224),
                    transforms.Lambda
                    (lambda crops: torch.stack([transforms.ToTensor()(crop) for crop in crops])),
                    transforms.Lambda
                    (lambda crops: torch.stack([normalize(crop) for crop in crops]))
                ])
        )
    else:
        test_dataset = ChestXrayDataSetTest(image_list_file=TEST_LIST,
                                        transform=transforms.Compose([
                                            transforms.Resize(256),
                                            transforms.TenCrop(224),
                                            transforms.Lambda
                                            (lambda crops: torch.stack([transforms.ToTensor()(crop) for crop in crops])),
                                            transforms.Lambda
                                            (lambda crops: torch.stack([normalize(crop) for crop in crops]))
                                        ]),
                                        combine_pneumonia=args.combine_pneumonia)
    
    test_loader = DataLoader(dataset=test_dataset, batch_size=64,
                    shuffle=False, num_workers=8, pin_memory=True)

    # initialize the output tensor
    if USE_GPU:
        pred = torch.FloatTensor().cuda()
#         gt = torch.FloatTensor().cuda()
    else:
        pred=torch.FloatTensor()
#         gt = torch.FloatTensor()
#     gt = torch.FloatTensor()
    pred_names = []

    # switch to evaluate mode
    model.eval()

    for i, (inputs, names) in tqdm(enumerate(test_loader), total=len(test_loader)):
        
        if USE_GPU:
            inputs = inputs.cuda()
#             labels = labels.cuda()
        
#         gt = torch.cat((gt, labels), 0)


        # Shape of input == [BATCH_SIZE, NUM_CROPS=10, CHANNELS=3, HEIGHT=224, WIDTH=244]
        bs, n_crops, c, h, w = inputs.size()
        inputs = torch.autograd.Variable(inputs.view(-1, c, h, w), volatile=True)

        # Pass through the network and take average prediction from all the crops
        output,_,_ = model(inputs)
        output_mean = output.view(bs, n_crops, -1).mean(1)
        pred = torch.cat((pred, output_mean.data), 0)
        pred_names += names
        del inputs

    
    if USE_GPU:
        pred = pred.cpu().numpy()
#         gt = gt.cpu().numpy()

    else:
        pred=pred.numpy()
#         gt=pred.numpy()


    assert len(pred) == len(pred_names)
    if args.binary_eval:
        pred = pred_converter(pred)

    scores = []
    for p,  n in zip(pred, pred_names):
        p = ["%.1f %%" % (i * 100) for i in p]
#         l = np.argmax(l)
        scores.append([n] + p)

    header=['Name', 'Normal', 'Bacterial', 'Viral', 'COVID-19']
    alignment="c"*5
    if args.combine_pneumonia:
        header = ['Name', 'Normal', 'Pneumonia', 'COVID-19']
        alignment = "c"*4
    if args.binary_eval:
        header=["Name", "Non-Covid", "Covid"]
#     string = tt.to_string(
#         scores,
#         header=header,
#         style=tt.styles.ascii_thin_double,
#         padding=(0, 1),
#         alignment=alignment
#     )

#     print (string)

    predsFile=os.path.join(args.visualize_dir,'preds.txt')
    f=open(predsFile,"w")
    pprint(header,f)
    pprint(scores,f)
    f.close()
    
    # RISE Visualization
    if args.visualize_dir:
        visualize(model,args.img_dir,args.visualize_dir,CovidDataLoader)
        print("Visualizations generated at "+str(args.visualize_dir))