import scipy.signal as sg
import xml.etree.ElementTree as ET
import h5py
import pandas as pd
import numpy as np

from release.constants import WELCH_NPERSEG, ALPHA_BAND


def rt_emulate(wfilter, x, chunk_size=1):
    """
    Emulate realtime filter chunks processing
    :param wfilter: filter instance
    :param x: signal to process
    :param chunk_size: length of chunk
    :return: filtered signal
    """
    y = [wfilter.apply(x[k:k+chunk_size]) for k in range(0, len(x), chunk_size)]
    if len(x) % chunk_size:
        y += [wfilter.apply(x[len(x) - len(x)%chunk_size:])]
    return np.concatenate(y)


def band_hilbert(x, fs, band, N=None, axis=-1):
    """
    Non-causal bandpass Hilbert transform to reconstruct analytic narrow-band signal
    :param x: input signal
    :param fs: sampling frequency
    :param band: band of interest
    :param N: fft n parameter
    :param axis: fft axis parameter
    :return: analytic narrow-band signal
    """
    x = np.asarray(x)
    Xf = np.fft.fft(x, N, axis=axis)
    w = np.fft.fftfreq(N or x.shape[0], d=1. / fs)
    Xf[(w < band[0]) | (w > band[1])] = 0
    x = np.fft.ifft(Xf, axis=axis)[:x.shape[0]]
    return 2*x


class SlidingWindowBuffer:
    def __init__(self, n_taps, dtype='float'):
        """
        Sliding window buffer implement wrapper for numpy array to store last n_taps samples of dtype (util class)
        :param n_taps: length of the buffer
        :param dtype: buffer dtype
        """
        self.buffer = np.zeros(n_taps, dtype)
        self.n_taps = n_taps

    def update_buffer(self, chunk):
        if len(chunk) < len(self.buffer):
            self.buffer[:-len(chunk)] = self.buffer[len(chunk):]
            self.buffer[-len(chunk):] = chunk
        else:
            self.buffer = chunk[-len(self.buffer):]
        return self.buffer


def _interval_mask(x, left, right):
    """
    Boolean interval mask
    :return: x \in [left, right]
    """
    return (x >= left) & (x <= right)


def _interval_flankers_mask(x, left, right, flanker_width):
    """
    Boolean flankers mask
    :return: x \in [left-flanker_width, left] and [right, right + flanker_width]
    """
    mask_l = _interval_mask(x, left - flanker_width, left)
    mask_r = _interval_mask(x, right, right + flanker_width)
    return mask_l | mask_r


def magnitude_spectrum(x, fs, nperseg=WELCH_NPERSEG, return_onesided=False):
    """
    Welch magnitude spectrum
    :param x: signal
    :param fs: sampling frequency
    :return: freq, magn_spectrum
    """
    freq, time, pxx = sg.stft(x, fs, nperseg=nperseg, return_onesided=return_onesided, noverlap=int(nperseg*0.9))
    pxx = np.median(np.abs(pxx), 1)
    return freq, pxx


def individual_max_snr_band(x, fs, initial_band=ALPHA_BAND, band_half_width=None, snr_flanker_width=None):
    """
    Specify initial band to individual band by maximizing SNR
    :param x: signal
    :param fs: sampling frequency
    :param initial_band: initial band of search
    :param band_half_width: target band half width, if None set to initial band half width
    :param snr_flanker_width: flankers width to compute SNR, if None set to initial band half width
    :return: band, SNR
    """
    band_half_width = band_half_width or (ALPHA_BAND[1] - ALPHA_BAND[0]) / 2
    snr_flanker_width = snr_flanker_width or (ALPHA_BAND[1] - ALPHA_BAND[0]) / 2
    freq, pxx = magnitude_spectrum(x, fs)
    search_band_mask = _interval_mask(freq, *initial_band)
    best_snr = 0
    best_band = initial_band
    for main_freq in freq[search_band_mask]:
        band = (main_freq - band_half_width, main_freq + band_half_width)
        band_mean_mag = pxx[_interval_mask(freq, *band)].mean()
        flankers_mean_mag = pxx[_interval_flankers_mask(freq, *band, snr_flanker_width)].mean()
        snr = (band_mean_mag - flankers_mean_mag) / flankers_mean_mag
        if snr>best_snr:
            best_snr = snr
            best_band = band
    return best_band, best_snr


def delay_align(x, y, delay):
    """
    Method to align offline and real-time signals by delay
    :param x: real-time prediction
    :param y: offline target signal
    :param delay: delay
    :return: x and y with compensated delay
    """
    if delay >= 0:
        x = x[delay:]
        y = y[:-delay or None]
    else:
        x = x[:delay]
        y = y[abs(delay):]
    return x, y


def _get_channels_and_fs(xml_str_or_file):
    root = ET.fromstring(xml_str_or_file)
    if root.find('desc').find('channels') is not None:
        channels = [k.find('label').text for k in root.find('desc').find('channels').findall('channel')]
    else:
        channels = [k.find('name').text for k in root.find('desc').findall('channel')]
    fs = int(root.find('nominal_srate').text)
    return channels, fs


def _get_signals_list(xml_str):
    root = ET.fromstring(xml_str)
    derived = [s.find('sSignalName').text for s in root.find('vSignals').findall('DerivedSignal')]
    composite = []
    if root.find('vSignals').findall('CompositeSignal')[0].find('sSignalName') is not None:
        composite = [s.find('sSignalName').text for s in root.find('vSignals').findall('CompositeSignal')]
    return derived + composite


def _get_info(f):
    if 'channels' in f:
        channels = [ch.decode("utf-8")  for ch in f['channels'][:]]
        fs = f['fs'].value
    else:
        channels, fs = _get_channels_and_fs(f['stream_info.xml'][0])
    signals = _get_signals_list(f['settings.xml'][0])
    n_protocols = len([k for k in f.keys() if ('protocol' in k and k != 'protocol0')])
    block_names = [f['protocol{}'.format(j+1)].attrs['name'] for j in range(n_protocols)]
    return fs, channels, block_names, signals


def load_data(file_path):
    """
    Load experimental data from file_path
    :param file_path: experiment dataset file path
    :return: df - DataFrame with exp.data, fs - sampling frequency, channels - channels names, p_names - blocks names
    """
    with h5py.File(file_path) as f:
        # load meta info
        fs, channels, p_names, signals = _get_info(f)

        # load raw data
        data = [f['protocol{}/raw_data'.format(k + 1)][:] for k in range(len(p_names))]
        df = pd.DataFrame(np.concatenate(data), columns=channels)

        # load signals data
        signals_data = [f['protocol{}/signals_data'.format(k + 1)][:] for k in range(len(p_names))]
        df_signals = pd.DataFrame(np.concatenate(signals_data), columns=['signal_'+s for s in signals])
        df = pd.concat([df, df_signals], axis=1)

        # load timestamps
        if 'timestamp' in df:
            timestamp_data = [f['protocol{}/timestamp_data'.format(k + 1)][:] for k in range(len(p_names))]
            df['timestamps'] = np.concatenate(timestamp_data)

        # events data
        events_data = [f['protocol{}/mark_data'.format(k + 1)][:] for k in range(len(p_names))]
        df['events'] = np.concatenate(events_data)

        # set block names and numbers
        df['block_name'] = np.concatenate([[p]*len(d) for p, d in zip(p_names, data)])
        df['block_number'] = np.concatenate([[j + 1]*len(d) for j, d in enumerate(data)])
    return df, fs, channels, p_names

if __name__ == "__main__":
    x = np.arange(5)
    print(_interval_mask(x, 1, 2))
    print(_interval_flankers_mask(x, *[1, 2], 1))
    x = np.random.normal(size=100000)
    x = sg.filtfilt(*sg.butter(1, np.array(ALPHA_BAND)/500*2, 'band'), x)
    print(individual_max_snr_band(x, 500))


