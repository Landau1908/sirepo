# -*- coding: utf-8 -*-
"""Wrapper to run Warp VND/WARP from the command line.

:copyright: Copyright (c) 2017 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from __future__ import absolute_import, division, print_function
from pykern import pkio
from pykern.pkdebug import pkdp, pkdc
from sirepo import mpi
from sirepo import simulation_db
from sirepo.template import template_common
import h5py
import numpy as np
import sirepo.template.warpvnd as template


def run(cfg_dir):
    with pkio.save_chdir(cfg_dir):
        exec(_script(), locals(), locals())
        data = simulation_db.read_json(template_common.INPUT_BASE_NAME)

        if data['report'] == 'fieldReport':
            if len(potential.shape) == 2:
                values = potential[xl:xu, zl:zu]
            else:
                # 3d results
                values = potential[xl:xu, int(NUM_Y / 2), zl:zu]
            res = _generate_field_report(data, values, {
                'tof_expected': tof_expected,
                'steps_expected': steps_expected,
                'e_cross': e_cross,
            })
        elif data['report'] == 'fieldComparisonReport':
            wp.step(template.COMPARISON_STEP_SIZE)
            res = template.generate_field_comparison_report(data, cfg_dir)
        else:
            raise RuntimeError('unknown report: {}'.format(data['report']))
    simulation_db.write_result(res)


def run_background(cfg_dir):
    """Run warpvnd in ``cfg_dir`` with mpi

    Args:
        cfg_dir (str): directory to run warpvnd in
    """
    with pkio.save_chdir(cfg_dir):
        #TODO(pjm): disable running with MPI for now
        # mpi.run_script(_script())
        exec(_script(), locals(), locals())
        simulation_db.write_result({})


def _generate_field_report(data, values, res):
    grid = data['models']['simulationGrid']
    plate_spacing = grid['plate_spacing'] * 1e-6
    beam = data['models']['beam']
    radius = grid['channel_width'] / 2. * 1e-6

    if np.isnan(values).any():
        return {
            'error': 'Results could not be calculated.\n\nThe Simulation Grid may require adjustments to the Grid Points and Channel Width.',
        }
    return {
        'aspect_ratio': 6.0 / 14,
        'x_range': [0, plate_spacing, len(values[0])],
        'y_range': [- radius, radius, len(values)],
        'x_label': 'z [m]',
        'y_label': 'x [m]',
        'title': 'ϕ Across Whole Domain',
        'z_matrix': values.tolist(),
        'frequency_title': 'Volts',
        'tof_expected': res['tof_expected'],
        'steps_expected': res['steps_expected'],
        'e_cross': res['e_cross'],
    }


def _script():
    return pkio.read_text(template_common.PARAMETERS_PYTHON_FILE)
