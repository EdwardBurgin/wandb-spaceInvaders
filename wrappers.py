from collections import deque
import gym
import numpy as np
import cv2

class ImageProcessWrapper(gym.ObservationWrapper):
    # Preprocessing image 
    # Crop , resize, convert to gray and kept 3D
    def __init__(self,env=None):
        super().__init__(env)
        self.observation_space = gym.spaces.Box(low=0,high=255,shape=(88,64,1),dtype=np.uint8)
    def observation(self,obs):
        obs = obs[25:200,15:145]
        obs = cv2.resize(obs,(64,88),interpolation=cv2.INTER_AREA)
        obs = cv2.cvtColor(obs, cv2.COLOR_RGB2GRAY)
        obs = np.expand_dims(obs,2)
        return obs 

class FrameStackWrapper(gym.ObservationWrapper):
    def __init__(self, env, n_steps=4):
        super().__init__(env)
        old_space = env.observation_space
        self.observation_space = gym.spaces.Box(
            old_space.low .repeat(n_steps, axis=2)
        ,   old_space.high.repeat(n_steps, axis=2)
        ,   dtype=np.uint8
        )

    def reset(self):
        self.buffer = np.zeros_like(self.observation_space.low, dtype=np.uint8)
        return self.observation(self.env.reset())

    def observation(self, observation):
        self.buffer[:,:,:-1] = self.buffer[:,:,1:]
        self.buffer[:,:,-1:] = observation
        return self.buffer

class MaxAndSkipWrapper(gym.Wrapper):
    # Apply each step 'skip' times with the same action
    # return obs as the max over the last 2 obs, to avoid clipping
    def __init__(self,env,skip=4):
        super().__init__(env)
        self._skip = skip
    def step(self,action):
        total_reward = 0
        done = False
        for _ in range(self._skip):
            obs,reward,done,info=self.env.step(action)
            total_reward += reward
            self._obs_buffer[0] = self._obs_buffer[1]
            self._obs_buffer[1] = obs
            if done:
                break
        max_obs = np.max(self._obs_buffer,axis=0)
        return max_obs,total_reward,done,info
    def reset(self):
        self._obs_buffer = np.zeros( (2,)+self.env.observation_space.shape,dtype=np.uint8)
        obs = self.env.reset()
        self._obs_buffer[1] = obs
        return obs

class ClipRewardWrapper(gym.Wrapper):
    # Reduce rewards to +1 0 or -1
    def step(self,action):
        obs,reward,done,info=self.env.step(action)
        return obs,np.sign(reward),done,info

