import numpy as np
import argparse
import losses
import keras
import time
import matplotlib
from os import path, remove
import healpy as hp
from sys import stderr
from cnn_healpix import create_model

def get_loss(loss):
    # try to find loss by name in losses module
    # if not found use string as is
    try:
        loss = getattr(losses, loss)
    except AttributeError:
        pass
    return loss

def get_source_data(source_id):
    if source_id == 'M82':
        source_lon = 141.4095
        source_lat = 40.5670
        D_src = '3.5'  # Mpc
    elif source_id == 'CenA':
        source_lon = 309.5159
        source_lat = 19.4173
        D_src = '3.5'  # Mpc
    elif source_id == 'NGC253':
        source_lon = 97.3638
        source_lat = -87.9645
        D_src = '3.5'  # Mpc
    elif source_id == 'NGC6946':
        source_lon = 95.71873
        source_lat = 11.6729
        D_src = '6.0'
    elif source_id == 'M87':
        source_lon = 283.7777
        source_lat = 74.4912
        D_src = '18.5'  # Mpc
    elif source_id == 'FornaxA':
        source_lon = 240.1627
        source_lat = -56.6898
        D_src = '20.0'  # Mpc
    else:
        raise ValueError('Unknown source!')
    return source_lon, source_lat, D_src

def load_src_sample(args):
    import lzma
    _, _, D_src = get_source_data(args.source_id)

    infile = ('src_sample_' + args.source_id + '_D' + D_src
              + '_Emin' + str(args.Emin)
              + '_N' + str(args.Nini)
              + '_R' + str(args.source_vicinity_radius)
              + '_Nside' + str(args.Nside)
              + '.txt.xz')
    infile = args.data_dir + '/' + args.mf + '/sources/' + infile
    try:
        with lzma.open(infile, 'rt') as f:
            data = np.genfromtxt(f, dtype=float)
    except IOError:
        print('\n-------> ' + infile + ' file not found!')
        print('-------> Create one with [convert_]src_sample.py\n')
        exit(1)
    return data


def f_sampler(args, n_samples=0):  # if <= 0, sample forever
    Neecr = args.Neecr
    Fsrc = None
    if 0 <= args.f_src <= 1.:
        Fsrc = args.f_src
    else:
        assert 0 <= args.f_src_min < 1
        assert 0 < args.f_src_max <= 1
        assert args.f_src_min < args.f_src_max

        N_src_min = np.round(args.f_src_min * Neecr)
        N_src_max = np.round(args.f_src_max * Neecr)
        if N_src_min == N_src_max:
            Fsrc = N_src_min / Neecr
        elif args.log_sample:
            if args.f_src_min == 0:
                # make sure roughly equal amount of isotropic and mixture samples are generated
                logNmin = np.log(1. / N_src_max)
            else:
                logNmin = np.log(args.f_src_min * Neecr)

            logNmax = np.log(args.f_src_max * Neecr)

    n = 0
    if Fsrc is not None:
        Nsrc = int(np.round(Neecr*Fsrc))

    while n != n_samples:
        if Fsrc is None:
            if args.log_sample:
                Nsrc = int(np.round(np.exp(logNmin + (logNmax-logNmin)*np.random.rand())))
                assert N_src_min <= Nsrc <= N_src_max
            else:
                Nsrc = np.random.randint(N_src_min, N_src_max+1)

        Niso = Neecr - Nsrc
        yield (Nsrc, Niso)

class SampleGenerator(keras.utils.Sequence):
    def __init__(self, args):
        self.add_iso = args.f_src_min > 0 or not args.log_sample

        self.n_batchs = int(np.ceil(args.n_samples / args.batch_size))
        batch_size = int(np.round(args.n_samples / self.n_batchs))
        if self.add_iso:
            batch_size = (batch_size//2)*2  # make sure batch_size is divisible of 2

        if batch_size != args.batch_size:
            print('batch size adjusted to ', batch_size, file=stderr)

        self.batch_size = batch_size

        data = load_src_sample(args)
        self.Neecr = args.Neecr
        #self.n_batches = n_batches

        self.Ncells = hp.nside2npix(args.Nside)
        self.sampler = f_sampler(args)

        # 2. Find non-zero lines, i.e., those with Z>0:
        tp = np.arange(0, np.size(data[:, 0]))
        nonz = tp[data[:, 5] > 0]
        self.nonz_number = len(nonz)
        assert self.nonz_number >= args.Neecr

        # These are numbers of cells on the healpix grid occupied by the
        # nuclei in the infile
        self.healpix_src_cells = data[nonz, 7].astype(int)


    def __len__(self):
        return self.n_batchs

    def __getitem__(self, idx):
        healpix_map = np.zeros((self.batch_size, self.Ncells), dtype=float)
        fractions = np.zeros(self.batch_size)
        for i in np.arange(0, self.batch_size):
            if self.add_iso and i%2 == 0:
                Nsrc = 0
                Niso = args.Neecr
            else:
                Nsrc, Niso = self.sampler.__next__()

            if Nsrc > 0:
                # Create a random sample of from-source events:
                src_sample = np.random.choice(self.nonz_number, Nsrc, replace=False)

                # Cells of the healpix grid "occupied" by the from-source sample
                src_cells = self.healpix_src_cells[src_sample]

                # This is a simple way to define the map. It assumes
                # only one EECR gets in a cell. Works OK for Nside=512.
                # healpix_map[src_cells] = 1

                # "cells" is an intermediate variable to simplify the code.
                # It consists of two arrays: [0] is a list of unique cells,
                # [1] is their multiplicity.
                cells = np.unique(src_cells, return_counts=True)
                healpix_map[cells[0]] += cells[1]

            if Niso > 0:
                # A sample of events from the isotropic background
                # np.random.seed(iso_random_seed)
                lon_iso = np.random.uniform(-np.pi, np.pi, Niso)
                lat_iso = np.arccos(np.random.uniform(-1, 1, Niso)) - np.pi / 2.

                # Cells "occupied" by the isotropic sample in the healpix grid
                iso_cells = hp.ang2pix(self.Nside, np.rad2deg(lon_iso),
                                       np.rad2deg(lat_iso), lonlat=True)

                # healpix_map[iso_cells] = 1
                # Similar to the above
                cells = np.unique(iso_cells, return_counts=True)
                healpix_map[cells[0]] += cells[1]

            if args.raw:
                pass
                # raw[i,:] = healpix_map

            fractions[i] = Nsrc / self.Neecr
            return fractions, healpix_map


class TestSampleGenerator(keras.utils.Sequence):
    def __init__(self, gen: SampleGenerator, seed=0, n_batches=10):
        self.gen = gen
        self.seed = seed
        self.n_batches = n_batches

    def __len__(self):
        return self.n_batches

    def __getitem__(self, idx):
        np.random.seed(idx + self.seed)
        return self.gen.__getitem__(idx)

def plot_learning_curves(history, save_file=None):
    metrics = ['loss'] + [m for m in history.history if m != 'loss' and not m.startswith('val_')]

    for i, m in enumerate(metrics):
        plt.subplot(len(metrics), 1, 1+i)
        plt.plot(history.history['val_' + m], 'r')
        plt.plot(history.history[m], 'g')
        plt.legend(['Test', 'Train'], loc='upper right')
        plt.ylabel(m)

    if save_file:
        plt.savefig(save_file)

    try:
        if args.show_fig:
            plt.show()
    except Exception:
        pass

if __name__ == '__main__':
    cline_parser = argparse.ArgumentParser(description='Train network')


    def add_arg(*pargs, **kwargs):
        cline_parser.add_argument(*pargs, **kwargs)


    add_arg('--f_src', type=float, help='fraction of "from-source" EECRs [0,1] or -1 for random', default=-1)
    add_arg('--Neecr', type=int, help='Total number of EECRs in each sample', default=500)
    add_arg('--Emin', type=int, help='Emin in EeV for which the input sample was generated', default=56)
    add_arg('--Nmixed_samples', type=int, help='Number of mixed samples (i.e., the sample size)', default=1000)
    add_arg('--source_id', type=str, help='source (CenA, NGC253, M82, M87 or FornaxA)', default='CenA')
    add_arg('--data_dir', type=str, help='data root directory (should contain jf/sources/ or pt/sources/)',
            default='data')
    add_arg('--mf', type=str, help='Magnetic field model (jf or pt)', default='jf')
    add_arg('--Nside', type=int, help='healpix grid Nside parameter', default=512)
    add_arg('--Nini', type=int, help='Size of the initial sample of from-source events', default=10000)
    add_arg('--log_sample', action='store_true', help="sample f_src uniformly in log scale")
    add_arg('--f_src_max', type=float, help='maximal fraction of "from-source" EECRs [0,1]', default=1)
    add_arg('--f_src_min', type=float, help='minimal fraction of "from-source" EECRs [0,1]', default=0)
    add_arg('--layers', type=str, help='comma-separated list of inner layer sizes', default='')
    add_arg('--output_prefix', type=str, help='output model file path prefix', default='')
    add_arg('--batch_size', type=int, help='size of training batch', default=1000)
    add_arg('--n_epochs', type=int, help='number of training epochs', default=100000)
    add_arg('--show_fig', action='store_true', help="Show learning curves")
    add_arg('--n_early_stop', type=int, help='number of epochs to monitor for early stop', default=30)
    add_arg('--pretrained', type=str, help='pretrained network', default='')
    add_arg('--loss', type=str, help='NN loss', default='binary_crossentropy')
    add_arg('--metrics', type=str, help='NN metrics', default='accuracy')
    add_arg('--n_samples', type=str, help='number of samples', default=100000)
    add_arg('--nside_min', type=str, help='minimal Nside for convolution', default=32)

    args = cline_parser.parse_args()

    if not args.show_fig:
        matplotlib.use('Agg')  # enable figure generation without running X server session


    import matplotlib.pyplot as plt

    inner_layers = [int(l) for l in args.layers.split(',') if len(l) > 0]

    args.loss = get_loss(args.loss)

    train_gen = SampleGenerator(args)
    val_gen = TestSampleGenerator(train_gen)
    test_gen = TestSampleGenerator(train_gen, seed=100000)


    def train_model(model, save_name, epochs=400, verbose=1, n_early_stop_epochs=30, batch_size=1024):
        for i in range(100000):
            save_path = save_name + "_v" + str(i) + '.h5'
            if not path.isfile(save_path):
                with open(save_path, mode='x') as f:
                    pass
                break

        weights_file = '/tmp/' + path.basename(save_path) + '_best_weights.h5'

        callbacks = []
        if n_early_stop_epochs > 0:
            callbacks = [
                keras.callbacks.ModelCheckpoint(weights_file, save_best_only=True, save_weights_only=True),
                # save best model
                keras.callbacks.EarlyStopping(monitor='val_loss', patience=n_early_stop_epochs, verbose=1)  # early stop
            ]
        t = time.time()

        history = model.fit_generator(train_gen, epochs=epochs, verbose=verbose,
                            validation_data=val_gen, callbacks=callbacks)
        t = time.time() - t
        if n_early_stop_epochs > 0 and path.isfile(weights_file):
            model.load_weights(weights_file)  # load best weights
            remove(weights_file)

        print('Training took %.0f sec' % t)
        model.save(save_path)
        print('Model saved in', save_path)

        plot_learning_curves(history, save_file=save_path[:-3] + '_train.png')

        score = model.evaluate_generator(test_gen, verbose=0)

        with open(save_path + '.score', mode='w') as out:
            for name, sc in zip(model.metrics_names, score):
                print(name, sc, file=out)
                print(name, sc)
            print('training_time_sec', t, file=out)

    model = create_model(train_gen.Ncells, nside_min=args.nside_min, inner_layer_sizes=inner_layers, pretrained=args.pretrained)
    if args.pretrained and len(args.output_prefix) == 0:
        save_name = args.pretrained[:-3]
    else:
        n_side_min = min(args.Nside, args.nside_min)
        l_first = 12*n_side_min*n_side_min
        save_name = args.output_prefix + 'Nside_{}-{}'.format(args.Nside, n_side_min) + "_L" + '_'.join([str(i) for i in [l_first] + inner_layers])

    train_model(model, save_name, batch_size=args.batch_size, epochs=args.n_epochs, n_early_stop_epochs=args.n_early_stop)
