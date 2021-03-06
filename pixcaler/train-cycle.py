import matplotlib
matplotlib.use('Agg')


import argparse
import os

import chainer
from chainer import training
from chainer.training import extensions
from chainer import serializers
from chainerui.utils import save_args
from chainerui.extensions import CommandsExtension

from pixcaler.net import Discriminator
from pixcaler.net import Generator, Pix2Pix
from pixcaler.updater import CycleUpdater
from pixcaler.dataset import AutoUpscaleDataset, Single32Dataset
from pixcaler.visualizer import out_image_cycle

def main():
    parser = argparse.ArgumentParser(
        description='chainer implementation of pix2pix',
    )
    parser.add_argument(
        '--batchsize', '-b', type=int, default=1,
        help='Number of images in each mini-batch',
    )
    parser.add_argument(
        '--epoch', '-e', type=int, default=200,
        help='Number of sweeps over the dataset to train',
    )
    parser.add_argument(
        '--base_ch', type=int, default=64,
        help='base channel size of hidden layer',
    )
    parser.add_argument(
        '--gpu', '-g', type=int, default=-1,
        help='GPU ID (negative value indicates CPU)',
    )
    parser.add_argument(
        '--dataset', '-i', default='./image/fsm',
        help='Directory of image files.',
    )
    parser.add_argument(
        '--out', '-o', default='result',
        help='Directory to output the result',
    )
    parser.add_argument(
        '--resume', '-r', default='',
        help='Resume the training from snapshot',
    )
    parser.add_argument(
        '--snapshot_interval', type=int, default=1000,
        help='Interval of snapshot',
    )
    parser.add_argument(
        '--display_interval', type=int, default=10,
        help='Interval of displaying log to console',
    )
    parser.add_argument(
        '--preview_interval', type=int, default=100,
        help='Interval of previewing generated image',    
    )
    args = parser.parse_args()
    save_args(args, args.out)

    print('GPU: {}'.format(args.gpu))
    print('# Minibatch-size: {}'.format(args.batchsize))
    print('# epoch: {}'.format(args.epoch))
    print('')
    
    upscaler = Pix2Pix(in_ch=4, out_ch=4, base_ch=args.base_ch)
    downscaler = Pix2Pix(in_ch=4, out_ch=4, base_ch=args.base_ch)

    if args.gpu >= 0:
        chainer.cuda.get_device(args.gpu).use()  # Make a specified GPU current
        upscaler.to_gpu()
        downscaler.to_gpu()

    # Setup an optimizer
    def make_optimizer(model, alpha=0.0002, beta1=0.5):
        optimizer = chainer.optimizers.Adam(alpha=alpha, beta1=beta1)
        optimizer.setup(model)
        optimizer.add_hook(chainer.optimizer.WeightDecay(0.00001), 'hook_dec')
        return optimizer
    opt_gen_up = make_optimizer(upscaler.gen)
    opt_dis_up = make_optimizer(upscaler.dis)

    opt_gen_down = make_optimizer(downscaler.gen)
    opt_dis_down = make_optimizer(downscaler.dis)


    train_l_d = AutoUpscaleDataset(
        "{}/trainA".format(args.dataset),
        random_nn=True,
    )
    train_s_d = Single32Dataset(
        "{}/trainB".format(args.dataset),
    )
    test_l_d = AutoUpscaleDataset(
        "{}/trainA".format(args.dataset),
        random_nn=False,
    )
    test_s_d = Single32Dataset(
        "{}/trainB".format(args.dataset),
    )

    train_l_iter = chainer.iterators.SerialIterator(train_l_d, args.batchsize)
    test_l_iter = chainer.iterators.SerialIterator(test_l_d, 1)
    train_s_iter = chainer.iterators.SerialIterator(train_s_d, args.batchsize)
    test_s_iter = chainer.iterators.SerialIterator(test_s_d, 1)
 
    # Set up a trainer
    updater = CycleUpdater(
        upscaler=upscaler,
        downscaler=downscaler,
        iterator={
            'main': train_l_iter,
            'trainB': train_s_iter,
            'testA': test_l_iter,            
            'testB': test_s_iter,
        },
        optimizer={
            'gen_up': opt_gen_up,
            'dis_up': opt_dis_up,
            'gen_down': opt_gen_down,
            'dis_down': opt_dis_down,
        },
        device=args.gpu,
    )
    trainer = training.Trainer(updater, (args.epoch, 'epoch'), out=args.out)

    snapshot_interval = (args.snapshot_interval, 'iteration')
    display_interval = (args.display_interval, 'iteration')
    preview_interval = (args.preview_interval, 'iteration')
    
    trainer.extend(extensions.snapshot(
        filename='snapshot_iter_{.updater.iteration}.npz'),
        trigger=snapshot_interval,
    )
    
    logging_keys = []
    trainer.extend(extensions.snapshot_object(
        upscaler.gen, 'gen_up_iter_{.updater.iteration}.npz'),
        trigger=snapshot_interval,
    )
    trainer.extend(extensions.snapshot_object(
        upscaler.dis, 'dis_up_iter_{.updater.iteration}.npz'),
        trigger=snapshot_interval,
    )
    logging_keys += [
        'gen_up/loss_adv',
        'gen_up/loss_rec',
        'dis_up/loss_real',
        'dis_up/loss_fake',
    ]

    trainer.extend(extensions.snapshot_object(
        downscaler.gen, 'gen_down_iter_{.updater.iteration}.npz'),
        trigger=snapshot_interval,
    )
    trainer.extend(extensions.snapshot_object(
        downscaler.dis, 'dis_down_iter_{.updater.iteration}.npz'),
        trigger=snapshot_interval,
    )
    logging_keys += [
        'gen_down/loss_adv',
        'gen_down/loss_rec',
        'dis_down/loss_real',
        'dis_down/loss_fake',
    ]

    trainer.extend(extensions.LogReport(trigger=preview_interval))
    trainer.extend(extensions.PlotReport(
        logging_keys,
        trigger=preview_interval,
    ))
    trainer.extend(extensions.PrintReport(
        ['epoch', 'iteration'] + logging_keys,
    ), trigger=display_interval)
    trainer.extend(extensions.ProgressBar(update_interval=10))
    trainer.extend(out_image_cycle(upscaler.gen, downscaler.gen, 8, args.out), trigger=preview_interval)
    trainer.extend(CommandsExtension())

    if args.resume:
        # Resume from a snapshot
        chainer.serializers.load_npz(args.resume, trainer)

    # Run the training
    trainer.run()

if __name__ == '__main__':
    main()
