# -*- coding: utf-8 -*-
"""Wrapper to run elegant from the command line.

:copyright: Copyright (c) 2015 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from __future__ import absolute_import, division, print_function
from pykern import pkio
from pykern import pkresource
from pykern import pksubprocess
from pykern.pkdebug import pkdp, pkdc
from sirepo import mpi
from sirepo import simulation_db
from sirepo.template import elegant_common
from sirepo.template import template_common
from sirepo.template.elegant import extract_report_data, ELEGANT_LOG_FILE
import copy
import os
import re


def run(cfg_dir):
    """Run elegant in ``cfg_dir``

    The files in ``cfg_dir`` must be configured properly.

    Args:
        cfg_dir (str): directory to run elegant in
    """
    with pkio.save_chdir(cfg_dir):
        _run_elegant(bunch_report=True)
        _extract_bunch_report()


def run_background(cfg_dir):
    """Run elegant as a background task

    Args:
        cfg_dir (str): directory to run elegant in
    """
    with pkio.save_chdir(cfg_dir):
        _run_elegant(with_mpi=True);
        simulation_db.write_result({})


def _run_elegant(bunch_report=False, with_mpi=False):
    exec(pkio.read_text(template_common.PARAMETERS_PYTHON_FILE), locals(), locals())
    if bunch_report and re.search('\&sdds_beam\s', elegant_file):
        return
    pkio.write_text('elegant.lte', lattice_file)
    ele = 'elegant.ele'
    pkio.write_text(ele, elegant_file)
    kwargs = {
        'output': ELEGANT_LOG_FILE,
        'env': elegant_common.subprocess_env(),
    }
    #TODO(robnagler) Need to handle this specially, b/c different binary
    if execution_mode == 'parallel' and with_mpi and mpi.cfg.cores > 1:
        return mpi.run_program(['Pelegant', ele], **kwargs)
    pksubprocess.check_call_with_signals(['elegant', ele], msg=pkdp, **kwargs)


def _extract_bunch_report():
    data = simulation_db.read_json(template_common.INPUT_BASE_NAME)
    if data['models']['bunchSource']['inputSource'] == 'sdds_beam':
        fn = 'bunchFile-sourceFile.{}'.format(data['models']['bunchFile']['sourceFile'])
    else:
        fn = 'elegant.bun'
    info = extract_report_data(
        fn,
        fn,
        data['models'][data['report']],
        data['models']['bunch']['p_central_mev'],
        0,
    )
    simulation_db.write_result(info)
