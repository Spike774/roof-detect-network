import numpy as np
import pdb  
import os #import the image files
import random #get random patches
import xml.etree.ElementTree as ET #traverse the xml files
from collections import defaultdict

from scipy import misc, ndimage #load images
import cv2

import experiment_settings as settings #getting constants
import json
from pprint import pprint

EXTENSION = '.png'

class Roof(object):
    '''Roof class containing info about its location in an image
    '''
    def __init__(self, roof_type=None, xmin=-1, xmax=-1, ymin=-1, ymax=-1, xcentroid=-1, ycentroid=-1):
        self.roof_type = roof_type
        self.xmin = xmin
        self.xmax = xmax
        self.ymin = ymin
        self.ymax = ymax
        # self.xcentroid = xcentroid
        # self.ycentroid = ycentroid

    def set_centroid(self):
        self.xcentroid = self.xmin+((self.xmax - self.xmin) /2)
        self.ycentroid = self.ymin+((self.ymax - self.ymin) /2)
    
    def get_roof_size(self):
        return ((self.ymax-self.ymin), (self.xmax-self.xmin))

    @property 
    def height(self):
        return (self.ymax-self.ymin)

    @property 
    def width(self):
        return (self.xmax-self.xmin)


    def check_overlap_total(self, patch_mask, patch_sum, img_rows, img_cols):
        roof_area = self.width*self.height
        curr_roof = np.zeros((img_rows, img_cols))
        curr_roof[self.ymin:self.ymin+self.height, self.xmin:self.xmin+self.width] = 1
        # misc.imsave('../viola_jones/1.jpg', curr_roof)
        curr_roof[patch_mask] = 0 
        # misc.imsave('../viola_jones/2.jpg', curr_roof)
        
        roof_area_found = roof_area-self.sum_mask(curr_roof)
        percent_found = ((roof_area_found)/roof_area)
        
        print percent_found
        return percent_found


    def sum_mask(self, array):
        '''Sum all ones in a binary array
        '''
        return np.sum(np.sum(array, axis=0), axis=0)


    def max_overlap_single_patch(self, rows=0, cols=0, detections=[]):
        '''Return maximum percentage overlap between this roof and a single patch in a set of candidate patches from the same image
        '''
        roof_area = self.width*self.height
        best_cascade = -1   #keep track of the 
        roof_mask = np.zeros((rows, cols))
        min_mask = np.zeros((rows, cols))
        min_mask[self.ymin:self.ymin+self.height, self.xmin:self.xmin+self.width] = 1
        for j, detection in enumerate(detections):
            for (x,y,w,h) in detection:                           #for each patch found
                roof_mask[self.ymin:self.ymin+self.height, self.xmin:self.xmin+self.width] = 1   #the roof
                roof_mask[y:y+h, x:x+w] = 0        #detection

                if self.sum_mask(roof_mask) == 0:                       #we have found the roof
                    return 1.0
                elif self.sum_mask(roof_mask) < self.sum_mask(min_mask):               #keep track of best match
                    min_mask = np.copy(roof_mask)                
                    x_true, y_true, w_true, h_true = x,y,w,h
                    best_cascade = j
        percent_found = (roof_area-self.sum_mask(min_mask))*(1.)/roof_area
        print 'Percent found: '+str(percent_found)+'  Best cascade: '+str(best_cascade)
        return percent_found


class DataAugmentation(object):
    def transform(self, Xb):
        self.Xb = Xb
        self.random_flip()
        self.random_rotation(10.)
        self.random_crop()
        return self.Xb

    def random_rotation(self, ang, fill_mode="nearest", cval=0.):
        angle = np.random.uniform(-ang, ang)
        self.Xb = scipy.ndimage.interpolation.rotate(self.Xb, angle, axes=(1,2), reshape=False, mode=fill_mode, cval=cval)

    def random_crop(self):
        #Extract 32 by 32 patches from 40 by 40 patches, rotate them randomly
        temp_Xb = np.zeros((self.Xb.shape[0],self.Xb.shape[1], CROP_SIZE, CROP_SIZE))
        margin = IMG_SIZE-CROP_SIZE
        for img in range(self.Xb.shape[0]):
            xmin = np.random.randint(0, margin)
            ymin = np.random.randint(0, margin)
            temp_Xb[img, :,:,:] = self.Xb[img, :, xmin:(xmin+CROP_SIZE), ymin:(ymin+CROP_SIZE)]
        self.Xb = temp_Xb


    @staticmethod
    def flip_save(img, img_path):
        img1 = cv2.flip(img,flipCode=0)
        cv2.imwrite('{0}_flip1.jpg'.format(img_path), img1)
        img2 = cv2.flip(img,flipCode=1)
        cv2.imwrite('{0}_flip2.jpg'.format(img_path), img2)
        img3 = cv2.flip(img,flipCode=-1)
        cv2.imwrite('{0}_flip3.jpg'.format(img_path), img3)


    @staticmethod
    def rotateImage(img, clockwise=True):
        #timg = np.zeros(img.shape[1],img.shape[0]) # transposed image
        if clockwise:
            # rotate counter-clockwise
            timg = cv2.transpose(img)
            cv2.flip(timg,flipCode=0)
            return timg
        else:
            # rotate clockwise
            timg = cv2.transpose(img)
            cv2.flip(timg,flipCode=1)
            return timg


    @staticmethod
    def add_padding(roof, padding, img_path):        
        try:
            img = cv2.imread(img_path)
        except IOError:
            print 'Cannot open '+img_path
        else:
            img_height, img_width, _ = img.shape
            if roof.xmin-padding > 0:
                roof.xmin -= padding
            if roof.ymin-padding > 0:
                roof.ymin -= padding
            if roof.xmin+roof.width+padding < img_width:
                roof.xmax += padding
            if roof.ymin+roof.height+padding < img_height:
                roof.ymax += padding
        roof.set_centroid()
        return roof


class DataLoader(object):
    def __init__(self, labels_path=None, out_path=None, in_path=None):
        self.total_patch_no = 0
        self.step_size = settings.PATCH_W/2

        assert out_path is not None and labels_path is not None and in_path is not None
        self.labels_path = labels_path
        self.out_path = out_path
        self.in_path = in_path


    def get_roofs_json(self, json_file):
        '''
        Return a list of roofs from a json file. We only have the centroids for these, not xmax, ymax
        '''
        img_dict = defaultdict()
        with open(json_file) as data_file:
            for line in data_file:
                img_json = json.loads(line)
                img_dict[img_json['image'].strip()] = img_json

        roof_dict = defaultdict(list)
        for img_name, img_info in img_dict.items():
            roof_list = img_info['roofs']

            for r in roof_list:
                roof_type = 'metal' if str(r['type']).strip() == 'iron' else 'thatch'
                roof = Roof(roof_type=roof_type, 
                            xmin=int(float(r['x'])), xmax=int(float(r['x'])),
                            ymin=int(float(r['y'])), ymax=int(float(r['y'])))

                padding = (settings.PATCH_W)/2
                roof = DataAugmentation.add_padding(roof, padding, settings.JSON_IMGS+img_name)
                roof_dict[str(img_name)].append(roof)

        return roof_dict


    def mark_detections_on_img(self, img_name=None, roofs=None):
        ''' Save an image with the detections and the ground truth roofs marked with rectangles
        '''
        assert img_name is not None and roofs is not None
        try:
            img = cv2.imread(self.in_path+img_name)
        except Exception, e:
            print e
            sys.exit(-1)
        else:
            for i, roof in enumerate(roofs):
                if roof.roof_type=='metal':
                    color=(255,0,0)
                elif roof.roof_type=='thatch':
                    color=(0,0,255)
                cv2.rectangle(img,(roof.xmin,roof.ymin),(roof.xmin+roof.width,roof.ymin+roof.height), color, 2)
            cv2.imwrite(self.out_path+'0_FULL_'+img_name[:-4]+'.jpg', img)

        return img



    def get_roofs(self, xml_file):
        '''Return list of Roofs

        Parameters
        ----------
        xml_file: string
            Path to XML file that contains roof locations for current image

        Returns
        ----------
        roof_list: list
            List of roof objects in an image as stated in its xml file
        max_w, max_h: int
            The integer value of the maximum width and height of all roofs in the current image
        '''
        tree = ET.parse(xml_file)
        root = tree.getroot()
        metal_list = list()
        thatch_list = list()
        
        for child in root:
            if child.tag == 'object':
                roof = Roof()
                for grandchild in child:
                    #get roof type
                    if grandchild.tag == 'action':
                        roof.roof_type = grandchild.text

                    #get positions of bounding box
                    if grandchild.tag == 'bndbox':
                        for item in grandchild:
                            pos = int(float(item.text))
                            pos = pos if pos >= 0 else 0
                            if item.tag == 'xmax':
                                roof.xmax = pos
                            elif item.tag == 'xmin':
                                roof.xmin = pos
                            elif item.tag  == 'ymax':
                                roof.ymax = pos
                            elif item.tag  == 'ymin':
                                roof.ymin = pos

                roof.set_centroid()
                if roof.roof_type == 'thatch':
                    thatch_list.append(roof)
                elif roof.roof_type == 'metal':
                    metal_list.append(roof)
                else:
                    raise TypeError('Unknown roof type {0} found'.format(roof.roof_type))

    return thatch_list, metal_list


    @staticmethod
    def get_img_names_from_path(path='', extension='.jpg'):
        ''' Get list of image files in a given folder path
        '''
        img_names = set()
        for file in os.listdir(path):
            if file.endswith(extension):
                img_names.add(file)
        return img_names


    def save_patch(self, img=None, xmin=-1, ymin=-1, roof_type=-1, extension=EXTENSION):
        '''Save a patch located at the xmin, ymin position to the patches folder 
        '''
        assert xmin > -1 and ymin > -1

        with open(self.labels_path, 'a') as labels_file:
            try:
                patch = img[ymin:(ymin+settings.PATCH_H), xmin:(xmin+settings.PATCH_W)]
                misc.imsave(self.out_path+str(self.total_patch_no)+str(extension), patch)
                
                #save an image showing where the patch was taken for debugging
                '''if settings.DEBUG:
                    img_copy = np.array(img, copy=True)
                    img_copy[ymin:(ymin+settings.PATCH_H), xmin:(xmin+settings.PATCH_W), 0:1] = 255
                    img_copy[ymin:(ymin+settings.PATCH_H), xmin:(xmin+settings.PATCH_W), 1:3] = 0
                    misc.imsave(settings.DELETE_PATH+str(self.total_patch_no)+'_DEL.jpg', img_copy)
                '''
            except (IndexError, IOError, KeyError, ValueError) as e:
                print e
            else:
                labels_file.write(str(self.total_patch_no)+','+str(roof_type)+'\n')
                print 'Saved patch: '+str(self.total_patch_no)+'\n'
                self.total_patch_no = self.total_patch_no+1


    def save_patch_scaled(self, roof=None, img=None, extension=EXTENSION):
        '''Save a downscaled image of a roof that is too large as is to fit within the PATCH_SIZE 
        '''
        roof_type = settings.METAL if roof.roof_type=='metal' else settings.THATCH

        h, w = roof.get_roof_size()
        #TODO: this might not be accurate: it doesn't make sense to scale up/down depending on...
        max_direction = max(w, h)
        xmin = roof.xcentroid-(max_direction/2)
        ymin = roof.ycentroid-(max_direction/2)
        xmax = roof.xcentroid+(max_direction/2)
        ymax = roof.ycentroid+(max_direction/2)

        with open(self.labels_path, 'a') as labels_file:
            try:
                patch = img[ymin:ymax, xmin:xmax]
                patch_scaled = misc.imresize(patch, (settings.PATCH_H, settings.PATCH_W))
                misc.imsave(self.out_path+str(self.total_patch_no)+extension, patch_scaled)
                
                #save an image showing where the patch was taken for debugging
                if settings.DEBUG:
                    #save a scaled version
                    mask_size = settings.PATCH_H
                    img_copy = np.array(img, copy=True)
                    img_copy[ymin:ymax, xmin:xmax, 0:1] = 255
                    img_copy[ymin:ymax, xmin:xmax, 1:3] = 0
                    misc.imsave(settings.DELETE_PATH+str(self.total_patch_no)+'_DEL_scaled.jpg', img_copy)

                    patch = img[ymin:ymax, xmin:xmax]
                    misc.imsave(settings.DELETE_PATH+str(self.total_patch_no)+'_DEL_NOTscaled.jpg', patch)

            except (IndexError, IOError, KeyError, ValueError) as e:
                print e

            else:
                labels_file.write(str(self.total_patch_no)+','+str(roof_type)+'\n')
                self.total_patch_no = self.total_patch_no+1


    def get_horizontal_patches(self, img=None, roof=None, y_pos=-1):
        '''Get patches along the width of a roof for a given y_pos (i.e. a given height in the image)
        '''
        roof_type = settings.METAL if roof.roof_type=='metal' else settings.THATCH

        h, w = roof.get_roof_size()
        hor_patches = ((w - settings.PATCH_W) // self.step_size) + 1  #hor_patches = w/settings.PATCH_W


        for horizontal in range(int(hor_patches)):
            x_pos = roof.xmin+(horizontal*self.step_size)
            self.save_patch(img= img, xmin=x_pos, ymin=y_pos, roof_type=roof_type)


    def overlap_percent(self, roof_list):
        '''Return the percent of overlap between the current patch and a roof bounding box
        Parameters:
        roof_list: list of Roofs
            roofs in current image
        '''
        raise ValueError


    def produce_roof_patches(self, img_path=None, img_id=-1, roof=None):
        '''Given a roof in an image, produce a patch or set of patches for it
        
        Parameters:
        ----------------
        img_loc: string path
            Path of image from which to obtain patches
        img_id: int
            id of the current image
        roof: Roof type
        label_file: 
               
        Returns:
        ---------------
        total_patch_no: int
            The number of patches produced so far
        '''
        assert img_id > -1 and roof is not None and img_path is not None

        try:
            img = cv2.imread(img_path)

        except IOError:
            print 'Cannot open '+img_path

        else:
            roof_type = settings.METAL if roof.roof_type=='metal' else settings.THATCH

            ybottom = (roof.ycentroid-(settings.PATCH_H/2) < 0)
            ytop = (roof.ycentroid+(settings.PATCH_H/2)>img.shape[0])
            xbottom = ((roof.xcentroid-(settings.PATCH_W/2)) < 0) 
            xtop = ((roof.xcentroid+(settings.PATCH_W/2))>img.shape[1])

            if ybottom or xbottom or ytop or xtop:
                #could not produce any patches
                print 'Failed to produce a patch \n'
                return -1

            h, w = roof.get_roof_size()

            #get a patch at the center
            self.save_patch(img= img, xmin=(roof.xcentroid-(settings.PATCH_W/2)), 
                            ymin=(roof.ycentroid-(settings.PATCH_H/2)), roof_type=roof_type)

            # if roof is too large, get multiple equally sized patches from it, and a scaled down patch also
            if w > settings.PATCH_W or h > settings.PATCH_H:
                x_pos = roof.xmin
                y_pos = roof.ymin

                vert_patches = ((h - settings.PATCH_H) // self.step_size) + 1  #vert_patches = h/settings.PATCH_H

                #get patches along roof height
                for vertical in range(int(vert_patches)):
                    y_pos = roof.ymin+(vertical*self.step_size)
                    #along roof's width
                    self.get_horizontal_patches(img=img, roof=roof, y_pos=y_pos)

                #get patches from the last row also
                if (h % settings.PATCH_W>0) and (h > settings.PATCH_H):
                    leftover = h-(vert_patches*settings.PATCH_H)
                    y_pos = y_pos-leftover
                    self.get_horizontal_patches(img=img, roof=roof, y_pos=y_pos)

                #add an image of entire roof, scaled down so it fits within patch size
                self.save_patch_scaled(img=img, roof=roof)
                

    def get_negative_patches(self, total_patches, label_file):
        print 'Getting the negative patches....\n'
        img_names = DataLoader.get_img_names_from_path(path=settings.UNINHABITED_PATH)

        negative_patches = (total_patches)/len(img_names)
        
        #Get negative patches
        for i, img_path in enumerate(img_names):
            settings.print_debug('Negative image: '+str(i))
            for p in range(negative_patches):
                #get random ymin, xmin, but ensure the patch will fall inside of the image
                try:
                    img = cv2.imread(settings.UNINHABITED_PATH+img_path)
                except IOError:
                    print 'Cannot open '+img_path
                else:
                    h, w, _ = img.shape
                    w_max = w - settings.PATCH_W
                    h_max = h - settings.PATCH_H
                    xmin = random.randint(0, w_max)
                    ymin = random.randint(0, h_max)

                    #save patch
                    self.save_patch(img=img, xmin=xmin, ymin=ymin, roof_type=settings.NON_ROOF) 


    def produce_xml_roofs(self):
        #Get the filename 
        img_names = DataLoader.get_img_names_from_path(path=settings.INHABITED_PATH)

        #Get the roofs defined in the xml, save the corresponding image patches
        f = open(settings.LABELS_PATH, 'w')
        f.close()
        
        metal_all = dict()
        thatch_all = dict()
        with open(settings.LABELS_PATH, 'w') as label_file:
            for i, img in enumerate(img_names):
                img_path = settings.INHABITED_PATH+img
                xml_path = settings.INHABITED_PATH+img[:-3]+'xml'

                thatch_roofs, metal_roofs = loader.get_roofs(xml_path)
                metal_roofs = [(m, img) for m in metal_roofs]
                thatch_roofs = [(m, img) for m in thatch_roofs]
                metal_all.extend(metal_roofs)
                thatch_all.extend(metal_roofs)
        
                
        thatch_train_index = np.random.choice(len(thatch_all), int(.80*len(thatch_all), replace=False)
        metal_train_index = np.random.choice(len(metal_all), int(.80*len(metal_all), replace=False)
        thatch_train = 
        
            #for i, img in enumerate(img_names_train):
                for r, roof in enumerate(metal_list):
                    loader.produce_roof_patches(img_path=img_path, img_id=i+1, 
                                        roof=roof, label_file=label_file)
            neg_patches_wanted = settings.NEGATIVE_PATCHES_NUM*loader.total_patch_no
            self.get_negative_patches(neg_patches_wanted, label_file)
            #settings.print_debug('************* Total patches saved: *****************: '+str(loader.total_patch_no))


    def produce_json_roofs(self, json_file=None):
        #Get the filename 
        img_names = DataLoader.get_img_names_from_path(path=settings.JSON_IMGS, extension='.png')
        roof_dict = self.get_roofs_json(json_file)
        
        with open(self.labels_path, 'w') as label_file:
            for i, img in enumerate(img_names, 1):
                print 'Procesing image {0}, number {1}'.format(img, i)
                self.mark_detections_on_img(img_name=img, roofs=roof_dict[img])
                
                # img_path = self.in_path+img
                # roof_list = roof_dict[img]

                # for r, roof in enumerate(roof_list):
                #     self.produce_roof_patches(img_path=img_path, img_id=i, roof=roof)

#     with open(settings.LABELS_PATH, 'w') as label_file:
#         max_w = 0
#         max_h = 0
#         for i, img in enumerate(img_names):
# #            print 'Processing image: '+str(i)+'\n'
#             img_path = settings.INHABITED_PATH+img
#             xml_path = settings.INHABITED_PATH+img[:-3]+'xml'

#             roof_list, cur_max_w, cur_max_h = loader.get_roofs(xml_path)
#            # max_h = cur_max_h if (max_h<cur_max_h) else max_h
#            # max_w = cur_max_w if (max_w<cur_max_h) else max_h

#             for r, roof in enumerate(roof_list):
# #                print 'Processing roof: '+str(r)+'\n'
#                 loader.produce_roof_patches(img_path=img_path, img_id=i+1, 
#                                     roof=roof, label_file=label_file, max_h=max_h, max_w=max_w)
#         neg_patches_wanted = settings.NEGATIVE_PATCHES_NUM*loader.total_patch_no
#         loader.get_negative_patches(neg_patches_wanted, label_file)
#         #settings.print_debug('************* Total patches saved: *****************: '+str(loader.total_patch_no))

if __name__ == '__main__':
    loader = DataLoader(labels_path='labels.csv', out_path='../data/testing_json/', in_path=settings.JSON_IMGS)
    loader.produce_json_roofs(json_file='../data/images-new/labels.json')
