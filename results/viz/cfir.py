import pandas as pd
import pylab as plt
import seaborn as sns
import numpy as np
from statsmodels.regression import yule_walker

from settings import FS
import scipy.signal  as sg
from pycfir.filters import CFIRBandEnvelopeDetector, band_hilbert, rt_emulate

DELAY = 0
dataset = "alpha2-delay-subj-21_12-06_12-15-09"
eeg_df = pd.read_pickle('data/rest_state_probes.pkl').query('dataset=="{}"'.format(dataset)).iloc[20000:30000]

eeg = eeg_df['eeg'].values
an_signal = eeg_df['an_signal'].values
band = eeg_df[['band_left_train', 'band_right_train']].values[0]
nor = lambda x: x/np.max(np.abs(x))

t0 = 1
slc = slice(6800, 7500)


stats_df = pd.read_pickle('results/stats.pkl').query('dataset=="{}" & delay=={} '.format(dataset, DELAY))

params = stats_df.query('method=="cfir" & metric=="corr"')['params'].values[0]
rect = CFIRBandEnvelopeDetector(band, FS, DELAY, params['n_taps'])
res = rect.apply(eeg)


t = np.arange(slc.stop-slc.start)/FS


filtered = np.nan * t* t.astype('complex')
filtered[(t > t0 - len(rect.b) / FS) & (t <= t0)] = nor(rect.b[::-1])



fig = plt.figure(figsize=(3, 8))
ax0 = fig.add_subplot(5,1,1)
ax0.plot(t, nor(eeg[slc]), '#0099d8')
ax0.plot(t, np.real(filtered), 'r', label='$b[-n]$')
ax0.plot(t, np.imag(filtered), 'r--')

ax0.text(t[0], 0.8, '$x$', color='#0099d8')
ax0.text(t[200], 0.8, '$b_{cfir}$', color='r')

ax = fig.add_subplot(5,1,2, sharex=ax0)
ax.plot(t, np.real(nor(res[slc])), '#0099d8')
ax.plot(t, np.imag(nor(res[slc])), '#0099d8', linestyle='--')
ax.text(t[0], 0.8, '$y_{cfir}$', color='#0099d8')

ax = fig.add_subplot(5,1,3, sharex=ax0)
ax.plot(t, nor(np.abs(res[slc])), '#0099d8')
ax.plot(t, nor(np.abs(an_signal[slc])), 'k', alpha=0.5)
#ax.plot(t, nor(np.abs(np.roll(an_signal, DELAY)[slc])), 'k--', alpha=0.5)
ax.text(t[260], 0.3, '$a_{cfir}$', color='#0099d8')
ax.text(t[200], 0.7, '$a$', color='#444444')



params = stats_df.query('method=="cfir" & metric=="phase"')['params'].values[0]
rect = CFIRBandEnvelopeDetector(band, FS, DELAY, params['n_taps'])

res = rect.apply(eeg)

ax = fig.add_subplot(5,1,4, sharex=ax0)
ax.plot(t, np.angle(res[slc]), '#0099d8')
ax.plot(t, np.angle(an_signal[slc]), 'k', alpha=0.5)
#ax.plot(t, np.angle(np.roll(an_signal, DELAY)[slc]), 'k--', alpha=0.5)
ax.text(t[0], np.pi+0.5, '$\phi_{cfir}$', color='#0099d8')
ax.text(t[-1], np.pi+0.5, '$\phi$', color='#444444')


for j, ax in enumerate(fig.axes):
    ax.get_yaxis().set_visible(False)
    ax.axvline(t0, color='k', alpha=0.2)
    ax.spines['bottom'].set_edgecolor('#6a747c')
    ax.spines['right'].set_visible(False)
    ax.spines['left'].set_visible(False)
    ax.spines['top'].set_visible(False)
    ax.spines['bottom'].set_position('zero')
    ax.tick_params(color='#6a747c')
    if j not in [2]:
        plt.setp(ax.get_xticklabels(), visible=False)
    if j == 2:
        ax.set_xlabel('Time, s')
        ax.xaxis.set_label_coords(0.9, -0.1)

ax.get_yaxis().set_visible(True)
ax.set_yticks([-np.pi, 0, np.pi])
ax.set_yticklabels(['$-\pi$', '0', '$\pi$'])
ax.spines['left'].set_visible(True)
ax.spines['left'].set_edgecolor('#6a747c')
fig.axes[0].set_title('$cfir$ \n $D = {}$ ms'.format(DELAY*2))
fig.subplots_adjust(hspace=1)

fig.savefig('results/viz/cfir.png', dpi=150)