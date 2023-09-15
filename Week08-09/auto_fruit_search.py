# M4 - Autonomous fruit searching

# basic python packages
import sys, os
import cv2
import numpy as np
import json
import argparse
import time
import math
from Astar import AStar
import plotting, env
import matplotlib.pyplot as plt
from path_smoothing import smooth_path

# import SLAM components
sys.path.insert(0, "{}/slam".format(os.getcwd()))
from slam.ekf import EKF
from slam.robot import Robot
import slam.aruco_detector as aruco

# import utility functions
sys.path.insert(0, "{}/util")
from pibot import PenguinPi
import measure as measure



def read_true_map(fname):
    """Read the ground truth map and output the pose of the ArUco markers and 5 target fruits&vegs to search for

    @param fname: filename of the map
    @return:
        1) list of targets, e.g. ['lemon', 'tomato', 'garlic']
        2) locations of the targets, [[x1, y1], ..... [xn, yn]]
        3) locations of ArUco markers in order, i.e. pos[9, :] = position of the aruco10_0 marker
    """
    with open(fname, 'r') as fd:
        gt_dict = json.load(fd)
        fruit_list = []
        fruit_true_pos = []
        aruco_true_pos = np.empty([10, 2])

        # remove unique id of targets of the same type
        for key in gt_dict:
            x = np.round(gt_dict[key]['x'], 1)
            y = np.round(gt_dict[key]['y'], 1)

            if key.startswith('aruco'):
                if key.startswith('aruco10'):
                    aruco_true_pos[9][0] = x
                    aruco_true_pos[9][1] = y
                else:
                    marker_id = int(key[5]) - 1
                    aruco_true_pos[marker_id][0] = x
                    aruco_true_pos[marker_id][1] = y
            else:
                fruit_list.append(key[:-2])
                if len(fruit_true_pos) == 0:
                    fruit_true_pos = np.array([[x, y]])
                else:
                    fruit_true_pos = np.append(fruit_true_pos, [[x, y]], axis=0)

        return fruit_list, fruit_true_pos, aruco_true_pos


def read_search_list():
    """Read the search order of the target fruits

    @return: search order of the target fruits
    """
    search_list = []
    with open('search_list.txt', 'r') as fd:
        fruits = fd.readlines()

        for fruit in fruits:
            search_list.append(fruit.strip())

    return search_list


def print_target_fruits_pos(search_list, fruit_list, fruit_true_pos):
    """Print out the target fruits' pos in the search order

    @param search_list: search order of the fruits
    @param fruit_list: list of target fruits
    @param fruit_true_pos: positions of the target fruits
    """

    print("Search order:")
    n_fruit = 1
    for fruit in search_list:
        for i in range(len(fruit_list)): # there are 5 targets amongst 10 objects
            if fruit == fruit_list[i]:
                print('{}) {} at [{}, {}]'.format(n_fruit,
                                                  fruit,
                                                  np.round(fruit_true_pos[i][0], 1),
                                                  np.round(fruit_true_pos[i][1], 1)))
        n_fruit += 1


# Waypoint navigation
# the robot automatically drives to a given [x,y] coordinate
# note that this function requires your camera and wheel calibration parameters from M2, and the "util" folder from M1
# fully automatic navigation:
# try developing a path-finding algorithm that produces the waypoints automatically
def drive_to_point(waypoint, robot_pose):
    # imports camera / wheel calibration parameters 
    
    ####################################################
    # TODO: replace with your codes to make the robot drive to the waypoint
    # One simple strategy is to first turn on the spot facing the waypoint,
    # then drive straight to the way point

    wheel_vel = 30 # tick
    target_theta = (np.arctan2((robot_pose[1,0]-waypoint[1]),(robot_pose[0,0]-waypoint[0]))/np.pi)*180
    if target_theta < 0:
        target_theta += 360
    print(target_theta)
    target_diff = target_theta - robot_pose[2]
    print(target_diff)
    if target_diff < 0:
        target_diff += 360
    # turn towards the waypoint
    
    if target_diff > 180:
        turn_time = float(baseline*np.abs(360-target_diff)*np.pi/(scale*wheel_vel*360)) # replace with your calculation
        print("Turning for {:.2f} seconds".format(turn_time))
        ppi.set_velocity([0, -1], turning_tick=wheel_vel, time=turn_time)
    else:
        turn_time = float(baseline*np.abs(target_diff)*np.pi/(scale*wheel_vel*360)) # replace with your calculation
        print("Turning for {:.2f} seconds".format(turn_time))
        ppi.set_velocity([0, 1], turning_tick=wheel_vel, time=turn_time)

    # calculate distance_travel
    distance_travel = np.sqrt((robot_pose[0,0]-waypoint[0])**2+(robot_pose[1,0]-waypoint[1])**2)
    #print(distance_travel)
    
    # after turning, drive straight to the waypoint
    drive_time = float(distance_travel/(wheel_vel*scale)) # replace with your calculation
    print("Driving for {:.2f} seconds".format(drive_time))
    ppi.set_velocity([1, 0], tick=wheel_vel, time=drive_time)
    ####################################################
    new_pose = np.array([waypoint[0],waypoint[1],target_theta])
    new_pose = new_pose.reshape((3,1))
    
    ekf.set_state_vector(new_pose)

    print("Arrived at [{}, {}]".format(waypoint[0], waypoint[1]))


def get_robot_pose():
    ####################################################
    # TODO: replace with your codes to estimate the pose of the robot
    # We STRONGLY RECOMMEND you to use your SLAM code from M2 here

    # update the robot pose [x,y,theta]
    robot_pose = ekf.get_state_vector() # replace with your calculation
    ####################################################

    return robot_pose

def parse_groundtruth(fname : str) -> dict:
    with open(fname,'r') as f:
        # gt_dict = ast.literal_eval(f.readline())
        gt_dict = json.load(f)
        aruco_dict = {}
        for key in gt_dict:
            if key.startswith("aruco"):
                aruco_num = int(key.strip('aruco')[:-2])
                aruco_dict[aruco_num] = np.reshape([gt_dict[key]["x"], gt_dict[key]["y"]], (2,1))
    return aruco_dict

# main loop
if __name__ == "__main__":
    parser = argparse.ArgumentParser("Fruit searching")
    parser.add_argument("--map", type=str, default='M4_true_map_full.txt') # change to 'M4_true_map_part.txt' for lv2&3
    parser.add_argument("--ip", metavar='', type=str, default='192.168.50.1')
    parser.add_argument("--port", metavar='', type=int, default=8080)
    parser.add_argument("--calib_dir", type=str, default="calibration/param/")
    args, _ = parser.parse_known_args()
    ip = args.ip
    datadir = args.calib_dir
    fileS = "{}scale.txt".format(datadir)
    scale = np.loadtxt(fileS, delimiter=',')
    if ip == 'localhost':
        scale /= 2
    fileK = "{}intrinsic.txt".format(datadir)
    camera_matrix = np.loadtxt(fileK, delimiter=',')
    fileD = "{}distCoeffs.txt".format(datadir)
    dist_coeffs = np.loadtxt(fileD, delimiter=',')
    fileB = "{}baseline.txt".format(datadir)
    baseline = np.loadtxt(fileB, delimiter=',')
    gt_aruco = parse_groundtruth(args.map)
    #print(gt_aruco)
    env1 = env.Env()
    env1.set_arena_size(3000,3000)
    for i in range(1,11):
        env1.add_square_obs(gt_aruco[i][0]*1000+1500, gt_aruco[i][1]*1000+1500, 100)
    #print(env1.obs) 

    robot = Robot(baseline, scale, camera_matrix, dist_coeffs)
    ekf = EKF(robot)

    ppi = PenguinPi(args.ip,args.port)

    # read in the true map
    #fruits_list, fruits_true_pos, aruco_true_pos = read_true_map(args.map)
    #search_list = read_search_list()
    #print_target_fruits_pos(search_list, fruits_list, fruits_true_pos)

    waypoint = [0.0,0.0]
    robot_pose = np.array(get_robot_pose())
    #print(robot_pose)

    # The following is only a skeleton code for semi-auto navigation
    while True:
        # enter the waypoints
        # instead of manually enter waypoints, you can give coordinates by clicking on a map, see camera_calibration.py from M2
        x,y,theta = 0.0,0.0,0.0
        x = input("X coordinate of the waypoint: ")
        try:
            x = float(x)
        except ValueError:
            print("Please enter a number.")
            continue
        y = input("Y coordinate of the waypoint: ")
        try:
            y = float(y)
        except ValueError:
            print("Please enter a number.")
            continue
        
        # estimate the robot's pose
        
        # robot drives to the waypoint
        waypoint = [x,y]
        drive_to_point(waypoint,robot_pose)
        #new_pose = np.array([waypoint[0], waypoint[1],np.arctan2((robot_pose[1]-waypoint[1]),robot_pose[0]-waypoint[0])/np.pi*180])
        #reshape = new_pose.reshape((3,1))
        #ekf.set_state_vector(reshape)
        robot_pose = get_robot_pose()
        print("Finished driving to waypoint: {}; New robot pose: {}".format(waypoint,robot_pose))

        # exit
        ppi.set_velocity([0, 0])
        uInput = input("Add a new waypoint? [Y/N]")
        if uInput == 'N':
            break
