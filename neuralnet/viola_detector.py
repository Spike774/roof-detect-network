import os
import sys
import getopt
import subprocess
import pdb
import math
from collections import defaultdict
import pickle
import csv

import numpy as np
import cv2
import cv
from scipy import misc, ndimage #load images

import utils
from timer import Timer

from reporting import Evaluation, Detections
import viola_detector_helpers
DEBUG = True

class ViolaDetector(object):
    def __init__(self, 
            in_path=None, 
            out_path=None,
            folder_name=None,
            save_imgs=False,
            detector_names=None, 
            group=None, #minNeighbors, scale...
            min_neighbors=3,
            scale=1.1,
            rotate=False, 
            removeOff=True,
            output_patches=True,
            check_both_detections=True #checks whether tehre is a match for either roof type with all detectors
            ):
        assert in_path is not None
        self.in_path = in_path
        assert out_path is not None
        self.out_folder = out_path
        self.out_folder_name = folder_name
        print 'Will output evaluation to: {0}'.format(self.out_folder)

        self.img_names = [f for f in os.listdir(in_path) if f.endswith('.jpg')]
        self.save_imgs = save_imgs

        #parameters for detection 
        self.scale = scale
        self.min_neighbors = min_neighbors
        self.group = group
        self.angles = utils.VIOLA_ANGLES if rotate else [0]
        self.remove_off_img = removeOff
        self.check_both_detectors = check_both_detectors

        self.viola_detections = Detections()
        self.setup_detectors(detector_names)

        self.evaluation = Evaluation(method='viola', folder_name=folder_name, out_path=self.out_folder, detections=self.viola_detections, 
                    in_path=self.in_path, detector_names=detector_names, output_patches=output_patches, check_both_detectors=check_both_detectors)


    def setup_detectors(self, detector_names=None, old_detector=False):
        '''Given a list of detector names, get the detectors specified
        '''
        #get the detectors
        assert detector_names is not None 
        self.roof_detectors = defaultdict(list)
        self.detector_names = detector_names

        for roof_type in ['metal', 'thatch']:
            for path in detector_names[roof_type]: 
                if path.startswith('cascade'):
                    start = '../viola_jones/cascades/' 
                    self.roof_detectors[roof_type].append(cv2.CascadeClassifier(start+path+'/cascade.xml'))
                    assert self.roof_detectors[roof_type][-1].empty() == False
                else:
                    self.roof_detectors[roof_type].append(cv2.CascadeClassifier('../viola_jones/cascade_'+path+'/cascade.xml'))


    def detect_roofs_in_img_folder(self):
        '''Compare detections to ground truth roofs for set of images in a folder
        '''
        for i, img_name in enumerate(self.img_names):
            print '************************ Processing image {0}/{1}\t{2} ************************'.format(i, len(self.img_names), img_name)
            self.detect_roofs(img_name)
            self.evaluation.score_img_rectified(img_name)
        self.evaluation.print_report()
        self.save_training_FP_and_TP()
        open(self.out_folder+'DONE', 'w').close() 


    def detect_roofs(self, img_name):
        try:
            rgb_unrotated = cv2.imread(self.in_path+img_name, flags=cv2.IMREAD_COLOR)
            gray = cv2.cvtColor(rgb_unrotated, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
        except IOError as e:
            print e
            sys.exit(-1)
        else:
            for roof_type, detectors in self.roof_detectors.iteritems():
                for i, detector in enumerate(detectors):
                    for angle in self.angles:

                        #for thatch we only need one angle
                        if roof_type == 'thatch' and angle > 0:
                            continue
                        print 'Detecting with detector: '+str(i)
                        print 'ANGLE '+str(angle)

                        with Timer() as t: 
                            rotated_image = utils.rotate_image(gray, angle) if angle>0 else gray
                            detections = self.detect_and_rectify(detector, rotated_image, angle, rgb_unrotated.shape[:2]) 
                            if self.group is not None:
                                pass
                                #detections = self.group(detections)
                        print 'Time detection: {0}'.format(t.secs)
                        self.viola_detections.total_time += t.secs
                        self.viola_detections.set_detections(roof_type=roof_type, img_name=img_name, 
                                angle=angle, detection_list=detections, img=rotated_image)

                        if DEBUG:
                            rgb_to_write = cv2.imread(self.in_path+img_name, flags=cv2.IMREAD_COLOR)
                            utils.draw_detections(detections, rgb_to_write)
                            cv2.imwrite('{0}{1}_{2}.jpg'.format(self.out_folder, img_name[:-4], angle), rgb_to_write)


    def detect_and_rectify(self, detector, image, angle, dest_img_shape):
        #do the detection
        detections = detector.detectMultiScale(image, scaleFactor=self.scale, minNeighbors=self.min_neighbors)
        #convert to proper coordinate system
        polygons = utils.convert_detections_to_polygons(detections)
        if DEBUG:
            pass
            #we can save the detections in the rotated image here
        #rotate back to original image coordinates
        if angle > 0:
            rectified_detections = utils.rotate_detection_polygons(polygons, image, angle, dest_img_shape, remove_off_img=self.remove_off_img)
        else:
            rectified_detections = polygons
        return rectified_detections


    def group_detections(self, detections):
        pass
        #GROUPING
        # TODO: fix the grouping
        # with Timer() as t:
        #     if self.group == 'group_rectangles':
        #         raise ValueError('We need to consider the angles here also')
        #         detected_roofs[roof_type][angle], weights = cv2.groupRectangles(np.array(detected_roofs[roof_type]).tolist(), 
        #                                                    min_neighbors, eps)
        #     elif self.group ==  'group_bounding':
        #         raise ValueError('We need to consider the angles here also')
        #         detected_roofs[roof_type][angle] = self.evaluation.get_bounding_rects(img_name=img_name, rows=1200, 
        #                     cols=2000, detections=detected_roofs[roof_type]) 
        #     else:
        #         pass

        #self.viola_detections.total_time += t.secs


    def mark_save_current_rotation(self, img_name, img, detections, angle, out_folder=None):
        out_folder = self.out_folder if out_folder is None else out_folder
        polygons = np.zeros((len(detections), 4, 2))
        for i, d in enumerate(detections):
            polygons[i, :] = utils.convert_rect_to_polygon(d)
        img = self.evaluation.mark_roofs_on_img(img_name=img_name, img=img, roofs=polygons, color=(0,0,255))
        path = '{0}_angle{1}.jpg'.format(out_folder+img_name[:-4], angle)
        print path
        cv2.imwrite(path, img)
        

    def save_training_FP_and_TP(self):
        '''Save the correct and incorrect detections so that the neural network can train on it
        '''
        #we want to write to the params folder of neuralnet
        general_path = utils.get_path(neural=True, data_fold=utils.TRAINING, in_or_out=utils.IN, out_folder_name=self.out_folder_name) 

        path_true = general_path+'true/'
        utils.mkdir(path_true)
         
        path_false = general_path+'false/'
        utils.mkdir(path_false)

        for img_name in self.img_names:
            try:
                img = cv2.imread(self.in_path+img_name, flags=cv2.IMREAD_COLOR)
            except:
                print 'Cannot open image'
                sys.exit(-1)

            for roof_type in ['metal', 'thatch']:
                good_d = self.viola_detections.good_detections[roof_type][img_name] 
                bad_d = self.viola_detections.bad_detections[roof_type][img_name]
                for path, detections in zip([path_true, path_false], [good_d, bad_d]):
                    img_debug = np.copy(img) #this is where we write the detections we're extraction. One image per roof type
                    utils.draw_detections(self.evaluation.correct_roofs[roof_type][img_name], img_debug, color=(0, 0, 0), thickness=2)

                    for i, detection in enumerate(detections):
                        #extract the patch, rotate it to a horizontal orientation, save it
                        warped_patch = utils.four_point_transform(img, detection)
                        cv2.imwrite('{0}{1}_{2}_roof{3}.jpg'.format(path, roof_type, img_name[:-4], i), warped_patch)
                        
                        #mark where roofs where taken out from for debugging
                        color = (0,255,0) if path==path_true else (0,0,255)
                        utils.draw_polygon(detection, img_debug, fill=False, color=color, thickness=2, number=i)

                    #write this type of extraction and the roofs to an image
                    extraction_type = 'good' if path == path_true else 'bad'
                    cv2.imwrite('{0}{1}_{2}_extract_{3}.jpg'.format(general_path, img_name[:-4], roof_type, extraction_type), img_debug)
            pdb.set_trace()


def main(detector_params=None, original_dataset=True, save_imgs=True, data_fold=utils.VALIDATION):
    combo_f_name = None
    try:
        opts, args = getopt.getopt(sys.argv[1:], "c:")
    except getopt.GetoptError:
        sys.exit(2)
        print 'Command line failed'
    for opt, arg in opts:
        if opt == '-c':
            combo_f_name = arg

    assert combo_f_name is not None
    detector = viola_detector_helpers.get_detectors(combo_f_name)

    viola = False if data_fold == utils.TRAINING else True
    in_path = utils.get_path(viola=viola, in_or_out=utils.IN, data_fold=data_fold)

    #name the output_folder
    folder_name = ['combo'+combo_f_name]
    for k, v in detector_params.iteritems():
        if k == 'output_patches':
            continue
        folder_name.append('{0}{1}'.format(k,v))
    folder_name = '_'.join(folder_name)

    out_path = utils.get_path(out_folder_name=folder_name, viola=True, in_or_out=utils.OUT, data_fold=data_fold)
    viola = ViolaDetector(out_path=out_path, in_path=in_path, folder_name = folder_name, save_imgs=save_imgs, 
                                        detector_names=detector,  **detector_params)
    viola.detect_roofs_in_img_folder()



if __name__ == '__main__':
    output_patches = True #if you want to save the true pos and false pos detections, you need to use the training set
    if output_patches:
        data_fold=utils.TRAINING
    else: 
        data_fold=utils.VALIDATION
    #data_fold=utils.SMALL_TEST
    
    # removeOff: whether to remove the roofs that fall off the image when rotating (especially the ones on the edge
    #group: can be None, group_rectangles, group_bounding
    # if check_both_detectors is True we check if either the metal or the thatch detector has found a detection that matches either type of roof 
    detector_params = {'output_patches': output_patches, 'check_both_detectors':True, 'min_neighbors':3, 'scale':1.08,
                                                                'group': None, 'rotate':True, 'removeOff':True} 
    main(detector_params=detector_params, save_imgs=True, data_fold=data_fold, original_dataset=True)
 
