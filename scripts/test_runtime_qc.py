import tempfile
import unittest
from pathlib import Path

from runtime_qc import num,payload


class RuntimeQcTests(unittest.TestCase):
 def test_nonfinite_normalized_value_is_rejected(self):
  with self.assertRaises(ValueError):num('nan')
 def test_waveform_station_identity_and_component_completeness_are_checked(self):
  import h5py
  root=Path(tempfile.mkdtemp());path=root/'synthetic.h5'
  with h5py.File(path,'w') as h:
   group=h.create_group('Waveforms/XX.WRONG')
   for component in ('E','N'):
    trace=group.create_dataset('XX.WRONG..BX'+component+'__synthetic',data=[0.0])
    trace.attrs['sampling_rate']=10.0
  report=payload(path,{'AX.AU090AM20p0'})
  self.assertIn('ASDF station identity differs from STATIONS',report['errors'])
  self.assertIn('not every station has exactly E,N,Z',report['errors'])


if __name__=='__main__':unittest.main()
