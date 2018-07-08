# -*- coding: utf-8 -*-
u"""?

:copyright: Copyright (c) 2017 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from __future__ import absolute_import, division, print_function
import pytest
from sirepo import feature_config

pytest.importorskip('srwl_bl')

def test_create_zip():
    from pykern import pkio
    from pykern import pkunit
    from pykern.pkdebug import pkdp, pkdpretty
    from pykern.pkunit import pkfail, pkok
    from sirepo import sr_unit
    import copy
    import zipfile

    fc = sr_unit.flask_client()
    imported = _import(fc)
    _codes = [
        ('elegant', 'bunchComp - fourDipoleCSR', ['WAKE-inputfile.knsl45.liwake.sdds', 'run.py', 'sirepo-data.json']),
        ('srw', 'Tabulated Undulator Example', ['magnetic_measurements.zip', 'run.py', 'sirepo-data.json']),
        ('warppba', 'Laser Pulse', ['run.py', 'sirepo-data.json']),
    ]
    codes_list = [x for x in _codes if x in feature_config.cfg.sim_types]
    print('=== codes_list: {} ==='.format(codes_list))
    for sim_type, sim_name, expect in imported + codes_list:
        sim_id = fc.sr_sim_data(sim_type, sim_name)['models']['simulation']['simulationId']
        resp = fc.sr_get(
            'exportArchive',
            {
                'simulation_type': sim_type,
                'simulation_id': sim_id,
                'filename': 'anything.zip',
            },
            raw_response=True,
        )
        with pkio.save_chdir(pkunit.work_dir()):
            fn = sim_name + '.zip'
            with open(fn, 'wb') as f:
                f.write(resp.data)
            z = zipfile.ZipFile(fn)
            nl = sorted(z.namelist())
            pkok(
                nl == expect,
                '{}: zip namelist incorrect, expect={}',
                nl,
                expect,
            )


def _import(fc):
    from pykern import pkio
    from pykern import pkunit
    import zipfile
    res = []
    for f in pkio.sorted_glob(pkunit.data_dir().join('*.zip')):
        with zipfile.ZipFile(str(f)) as z:
            expect = sorted(z.namelist() + ['run.py'])
        d = fc.sr_post_form(
            'importFile',
            {
                'file': (open(str(f), 'rb'), f.basename),
                'folder': '/exporter_test',
            },
        )
        res.append((d.simulationType, d.models.simulation.name, expect))
    return res
