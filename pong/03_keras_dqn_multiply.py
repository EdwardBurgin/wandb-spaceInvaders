#!/usr/bin/env python3
import wrappers

import argparse
import time,os
import numpy as np
import collections

# Tensorflow loading and configuration
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3' 
import tensorflow as tf
from tensorboardX import SummaryWriter

import keras


DEFAULT_ENV_NAME = "PongNoFrameskip-v4"
MEAN_REWARD_BOUND = 19.5

GAMMA = 0.99
BATCH_SIZE = 32
REPLAY_SIZE = 10000
LEARNING_RATE = 1e-4
SYNC_TARGET_FRAMES = 1000
REPLAY_START_SIZE = 10000
#REPLAY_START_SIZE = 1000

EPSILON_DECAY_LAST_FRAME = 10**5
EPSILON_START = 1.0
EPSILON_FINAL = 0.02


Experience = collections.namedtuple('Experience', field_names=['state', 'action', 'reward', 'done', 'new_state'])


class ExperienceBuffer:
    def __init__(self, capacity):
        self.buffer = collections.deque(maxlen=capacity)

    def __len__(self):
        return len(self.buffer)

    def append(self, experience):
        self.buffer.append(experience)

    def sample(self, batch_size):
        indices = np.random.choice(len(self.buffer), batch_size, replace=False)
        states, actions, rewards, dones, next_states = zip(*[self.buffer[idx] for idx in indices])
        return np.array(states), np.array(actions), np.array(rewards, dtype=np.float32), \
               np.array(dones, dtype=np.uint8), np.array(next_states)


class Agent:
    def __init__(self, env, exp_buffer):
        self.env = env
        self.exp_buffer = exp_buffer
        self._reset()

    def _reset(self):
        self.state = env.reset()
        self.total_reward = 0.0

    def play_step(self, net, epsilon=0.0):
        done_reward = None

        if np.random.random() < epsilon:
            action = env.action_space.sample()
        else:
            state_a = np.array([self.state], copy=False)
            q_vals = net.predict([state_a,np.ones((1,env.action_space.n))])
            action = np.argmax(q_vals)

        # do step in the environment
        new_state, reward, is_done, _ = self.env.step(action)
        self.total_reward += reward

        oneHotAction = [(i==action) for i in range(self.env.action_space.n)]
        exp = Experience(self.state, oneHotAction, reward, is_done, new_state)
        self.exp_buffer.append(exp)
        self.state = new_state
        if is_done:
            done_reward = self.total_reward
            self._reset()
        return done_reward

def DQN(input_shape,n_actions):
    X = I = keras.layers.Input(input_shape, name='frames')
    X = keras.layers.Conv2D(32,kernel_size=8,strides=4, activation='relu')(X)
    X = keras.layers.Conv2D(64,kernel_size=4,strides=2, activation='relu')(X)
    X = keras.layers.Conv2D(64,kernel_size=3,strides=1, activation='relu')(X)
    X = keras.layers.Flatten()(X)
    X = keras.layers.Dense(512, activation='relu')(X)
    X = keras.layers.Dense(n_actions)(X)

    J = keras.layers.Input((n_actions,), name='mask')

    O = keras.layers.Multiply()([X,J])

    model = keras.models.Model(inputs=[I,J], outputs=O)
    model.compile(loss='mse',optimizer=keras.optimizers.Adam(lr=LEARNING_RATE))

    return model


def calc_loss(batch, net, tgt_net):

    states, actions, rewards, dones, next_states = batch
    next_Q = tgt_net.predict([next_states,np.ones(actions.shape)])
    next_Q[dones==1] = 0
    targets = rewards + GAMMA*np.max(next_Q,axis=1) 

    net.train_on_batch([states,actions],actions*targets[:,None]) 


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", default=DEFAULT_ENV_NAME,
                        help="Name of the environment, default=" + DEFAULT_ENV_NAME)
    parser.add_argument("--reward", type=float, default=MEAN_REWARD_BOUND,
                        help="Mean reward boundary for stop of training, default=%.2f" % MEAN_REWARD_BOUND)
    parser.add_argument("--gpu",action="store_true",help="Run on the GPU, else only the CPU.")
    args = parser.parse_args()

    if not args.gpu:
        # Remove all GPUs
        tf.config.set_visible_devices([],'GPU')
    devices = tf.config.list_logical_devices()
    print("Tensorflow visible devices\n\t"+"\n\t".join(d.name for d in devices))

    env = wrappers.make_env(args.env,pytorch=False)
    env.reset()

    net = DQN(env.observation_space.shape, env.action_space.n)
    tgt_net = DQN(env.observation_space.shape, env.action_space.n)
    writer = SummaryWriter(comment="-" + args.env)
    #print(net.summary())

    buffer = ExperienceBuffer(REPLAY_SIZE)
    agent = Agent(env, buffer)
    epsilon = EPSILON_START

    total_rewards = []
    frame_idx = 0
    ts_frame = 0
    ts = time.time()
    best_mean_reward = None

    while True:
        frame_idx += 1
        epsilon = max(EPSILON_FINAL, EPSILON_START - frame_idx / EPSILON_DECAY_LAST_FRAME)

        reward = agent.play_step(net, epsilon)
        if reward is not None:
            total_rewards.append(reward)
            speed = (frame_idx - ts_frame) / (time.time() - ts)
            ts_frame = frame_idx
            ts = time.time()
            mean_reward = np.mean(total_rewards[-100:])
            print("%d: done %d games, reward %d mean reward %.3f, eps %.2f, speed %.2f f/s" % (
                frame_idx, len(total_rewards), reward , mean_reward, epsilon,
                speed
            ))
            writer.add_scalar("epsilon", epsilon, frame_idx)
            writer.add_scalar("speed", speed, frame_idx)
            writer.add_scalar("reward_100", mean_reward, frame_idx)
            writer.add_scalar("reward", reward, frame_idx)
            if best_mean_reward is None or best_mean_reward < mean_reward:
                net.save("log/"+args.env + "-best.h5")
                if best_mean_reward is not None:
                    print("Best mean reward updated %.3f -> %.3f, model saved" % (best_mean_reward, mean_reward))
                best_mean_reward = mean_reward
            if mean_reward > args.reward:
                print("Solved in %d frames!" % frame_idx)
                break

        if len(buffer) < REPLAY_START_SIZE:
            continue

        if frame_idx % SYNC_TARGET_FRAMES == 0:
            tgt_net.set_weights(net.get_weights())

        batch = buffer.sample(BATCH_SIZE)
        loss_t = calc_loss(batch, net, tgt_net)
    writer.close()
