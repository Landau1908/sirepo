# -*- coding: utf-8 -*-
u"""JSPEC execution template.

:copyright: Copyright (c) 2018 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""

from __future__ import absolute_import, division, print_function
from pykern import pkio
from pykern.pkdebug import pkdc, pkdp, pkdlog
from sirepo import simulation_db
from sirepo.template import template_common
import h5py
import re
import werkzeug

SIM_TYPE = 'synergia'

#TODO(pjm): change to True
WANT_BROWSER_FRAME_CACHE = False

_BEAM_EVOLUTION_OUTPUT_FILENAME = 'diagnostics.h5'

_COORD6 = ['x', 'xp', 'y', 'yp', 'z', 'zp']

_FILE_ID_SEP = '-'

_PLOT_LINE_COLOR = {
    'y1': '#1f77b4',
    'y2': '#ff7f0e',
    'y3': '#2ca02c',
}

_SCHEMA = simulation_db.get_schema(SIM_TYPE)


def background_percent_complete(report, run_dir, is_running):
    diag_file = run_dir.join(_BEAM_EVOLUTION_OUTPUT_FILENAME)
    if diag_file.exists():
        try:
            with h5py.File(str(diag_file), 'r') as f:
                size = f['emitx'].shape[0]
                return {
                    'percentComplete': 0,
                    'frameCount': size,
                }
        except Exception as e:
            # file present but not hdf formatted
            pass
    return {
        'percentComplete': 0,
        'frameCount': 0,
    }


def fixup_old_data(data):
    for m in ['beamEvolutionAnimation', 'simulationSettings']:
        if m not in data['models']:
            data['models'][m] = {}
            template_common.update_model_defaults(data['models'][m], m, _SCHEMA)


def get_animation_name(data):
    return 'animation'


def get_application_data(data):
    if data['method'] == 'get_particle_info':
        return _calc_particle_info(data['particle'])
    if data['method'] == 'calculate_bunch_parameters':
        return _calc_bunch_parameters(data['bunch'])


def import_file(request, lib_dir=None, tmp_dir=None):
    f = request.files['file']
    filename = werkzeug.secure_filename(f.filename)
    if re.search(r'.madx$', filename, re.IGNORECASE):
        data = _import_madx_file(f.read())
    else:
        raise IOError('invalid file extension, expecting .madx')
    data['models']['simulation']['name'] = re.sub(r'\.madx$', '', filename, re.IGNORECASE)
    return data


def get_simulation_frame(run_dir, data, model_data):
    frame_index = int(data['frameIndex'])
    if data['modelName'] == 'beamEvolutionAnimation':
        args = template_common.parse_animation_args(
            data,
            {
                '1': ['x', 'y1', 'y2', 'y3', 'startTime'],
                '': ['y1', 'y2', 'y3', 'startTime'],
            },
        )
        return _extract_evolution_plot(args, run_dir)

    raise RuntimeError('unknown animation model: {}'.format(data['modelName']))


def lib_files(data, source_lib):
    return []


def models_related_to_report(data):
    r = data['report']
    if r == 'animation':
        return []
    return [
        'simulation.visualizationBeamlineId',
        'bunch',
        'beamlines',
        'elements',
        r,
    ]


def python_source_for_model(data, model):
    return _generate_parameters_file(data)


def remove_last_frame(run_dir):
    pass


def write_parameters(data, run_dir, is_parallel):
    pkio.write_text(
        run_dir.join(template_common.PARAMETERS_PYTHON_FILE),
        _generate_parameters_file(data),
    )


#TODO(pjm): from template.elegant
def _add_beamlines(beamline, beamlines, ordered_beamlines):
    if beamline in ordered_beamlines:
        return
    for id in beamline['items']:
        id = abs(id)
        if id in beamlines:
            _add_beamlines(beamlines[id], beamlines, ordered_beamlines)
    ordered_beamlines.append(beamline)


#TODO(pjm): from template.elegant
def _build_beamline_map(data):
    res = {}
    for bl in data['models']['beamlines']:
        res[bl['id']] = bl['name']
    return res


def _calc_bunch_parameters(bunch):
    from synergia.foundation import Four_momentum
    bunch_def = bunch['beam_definition']
    mom = Four_momentum(bunch['mass'])
    try:
        if bunch_def == 'energy':
            mom.set_total_energy(bunch['energy'])
        elif bunch_def == 'momentum':
            mom.set_momentum(bunch['momentum'])
        elif bunch_def == 'gamma':
            mom.set_gamma(bunch['gamma'])
        else:
            assert False, 'invalid bunch def: {}'.format(bunch_def)
        bunch['gamma'] = _format_float(mom.get_gamma())
        bunch['energy'] = _format_float(mom.get_total_energy())
        bunch['momentum'] = _format_float(mom.get_momentum())
        bunch['beta'] = _format_float(mom.get_beta())
    except Exception as e:
        bunch[bunch_def] = ''
    return {
        'bunch': bunch,
    }


def _calc_particle_info(particle):
    from synergia.foundation import pconstants
    mass = 0
    charge = 0
    if particle == 'proton':
        mass = pconstants.mp
        charge = pconstants.proton_charge
    elif particle == 'antiproton':
        mass = pconstants.mp
        charge = pconstants.antiproton_charge
    elif particle == 'electron':
        mass = pconstants.me
        charge = pconstants.electron_charge
    elif particle == 'positron':
        mass = pconstants.me
        charge = pconstants.positron_charge
    elif particle == 'negmuon':
        mass = pconstants.mmu
        charge = pconstants.muon_charge
    elif particle == 'posmuon':
        mass = pconstants.mmu
        charge = pconstants.antimuon_charge
    else:
        assert False, 'unknown particle: {}'.format(particle)
    return {
        'mass': mass,
        'charge': str(charge),
    }


def _extract_evolution_plot(report, run_dir):
    plots = []
    with h5py.File(str(str(run_dir.join(_BEAM_EVOLUTION_OUTPUT_FILENAME))), 'r') as f:
        x = f['s'][:].tolist()
        y_range = None
        for yfield in ('y1', 'y2', 'y3'):
            if report[yfield] == 'none':
                continue
            points = _plot_values(f, report[yfield])
            if y_range:
                y_range = [min(y_range[0], min(points)), max(y_range[1], max(points))]
            else:
                y_range = [min(points), max(points)]
            plots.append({
                'points': points,
                'label': _plot_label(report[yfield], _SCHEMA['enum']['BeamColumn']),
                'color': _PLOT_LINE_COLOR[yfield],
            })
        return {
            'title': '',
            'x_range': [min(x), max(x)],
            'y_label': '',
            'x_label': 's [m]',
            'x_points': x,
            'plots': plots,
            'y_range': y_range,
        }


def _format_float(v):
    return float(format(v, '.10f'))


def _generate_lattice(data, beamline_map, v):
    beamlines = {}

    for bl in data['models']['beamlines']:
        if 'visualizationBeamlineId' in data['models']['simulation']:
            if int(data['models']['simulation']['visualizationBeamlineId']) == int(bl['id']):
                v['use_beamline'] = bl['name'].lower()
        beamlines[bl['id']] = bl

    ordered_beamlines = []

    for id in beamlines:
        _add_beamlines(beamlines[id], beamlines, ordered_beamlines)
    state = {
        'lattice': '',
        'beamline_map': beamline_map,
    }
    _iterate_model_fields(data, state, _iterator_lattice_elements)
    res = state['lattice']
    res = res[:-1]
    res += ';\n'

    for bl in ordered_beamlines:
        if len(bl['items']):
            res += '{}: LINE=('.format(bl['name'].upper())
            for id in bl['items']:
                sign = ''
                if id < 0:
                    sign = '-'
                    id = abs(id)
                res += '{},'.format(sign + beamline_map[id].upper())
            res = res[:-1]
            res += ');\n'
    return res


def _generate_parameters_file(data):
    _validate_data(data, _SCHEMA)
    v = template_common.flatten_data(data['models'], {})
    beamline_map = _build_beamline_map(data)
    v['lattice'] = _generate_lattice(data, beamline_map, v)
    template_name = 'parameters'
    if 'report' in data and data['report'] == 'bunchReport':
        template_name = 'bunch'
    return template_common.render_jinja(SIM_TYPE, v, 'base.py') \
        + template_common.render_jinja(SIM_TYPE, v, '{}.py'.format(template_name))


def _import_bunch(lattice, data):
    from synergia.foundation import pconstants
    ref = lattice.get_reference_particle()
    bunch = data['models']['bunch']
    bunch['beam_definition'] = 'gamma'
    bunch['charge'] = ref.get_charge()
    four_momentum = ref.get_four_momentum()
    bunch['gamma'] = _format_float(four_momentum.get_gamma())
    bunch['energy'] = _format_float(four_momentum.get_total_energy())
    bunch['momentum'] = _format_float(four_momentum.get_momentum())
    bunch['beta'] = _format_float(four_momentum.get_beta())
    bunch['mass'] = _format_float(four_momentum.get_mass())
    bunch['particle'] = 'other'
    if bunch['mass'] == pconstants.mp:
        if bunch['charge'] == pconstants.proton_charge:
            bunch['particle'] = 'proton'
        #TODO(pjm): antiproton (anti-proton) not working with synergia
    elif bunch['mass'] == pconstants.me:
        bunch['particle'] = 'positron' if bunch['charge'] == pconstants.positron_charge else 'electron'
    elif bunch['mass'] == pconstants.mmu:
        bunch['particle'] = 'posmuon' if bunch['charge'] == pconstants.antimuon_charge else 'negmuon'


def _import_elements(lattice, data):
    name_to_id = {}
    beamline = data['models']['beamlines'][0]
    current_id = beamline['id']

    for el in lattice.get_elements():
        attrs = {}
        for attr in el.get_double_attributes():
            attrs[attr] = el.get_double_attribute(attr)
        for attr in el.get_string_attributes():
            attrs[attr] = el.get_string_attribute(attr)
        for attr in el.get_vector_attributes():
            attrs[attr] = el.get_vector_attribute(attr)
        model_name = el.get_type().upper()
        m = template_common.model_defaults(model_name, _SCHEMA)
        if 'l' in attrs:
            attrs['l'] = float(str(attrs['l']))
        if model_name == 'DRIFT' and re.search(r'^auto_drift', el.get_name()):
            drift_name = 'D{}'.format(attrs['l']).replace('.', '_')
            m['name'] = drift_name
        else:
            m['name'] = el.get_name().upper()
        if m['name'] in name_to_id:
            beamline['items'].append(name_to_id[m['name']])
            continue
        m['type'] = model_name
        current_id += 1
        beamline['items'].append(current_id)
        m['_id'] = current_id
        name_to_id[m['name']] = m['_id']
        info = _SCHEMA['model'][model_name]
        for f in info.keys():
            if f in attrs:
                m[f] = attrs[f]
        for attr in attrs:
            if attr not in m:
                pkdlog('unknown attr: {}: {}'.format(model_name, attr))
        data['models']['elements'].append(m)
    data['models']['elements'] = sorted(data['models']['elements'], key=lambda el: (el['type'], el['name'].lower()))


def _import_madx_file(text):
    import synergia
    data = simulation_db.default_data(SIM_TYPE)
    reader = synergia.lattice.MadX_reader()
    reader.parse(text)
    lattice = _import_main_beamline(reader, data)
    _import_elements(lattice, data)
    _import_bunch(lattice, data)
    return data


def _import_main_beamline(reader, data):
    lines = {}
    for name in reader.get_line_names() + reader.get_sequence_names():
        names = []
        for el in reader.get_lattice(name).get_elements():
            names.append(el.get_name())
        lines[name] = names
    #TODO(pjm): assumes longest sequence is it target beamline
    beamline_name = _sort_beamlines_by_length(lines)[0][0]
    res = reader.get_lattice(beamline_name)
    current_id = 1
    data['models']['beamlines'].append({
        'id': current_id,
        'items': [],
        'name': beamline_name,
    })
    data['models']['simulation']['activeBeamlineId'] = current_id
    data['models']['simulation']['visualizationBeamlineId'] = current_id
    return res


#TODO(pjm): from template.elegant
def _iterate_model_fields(data, state, callback):
    for model_type in ['commands', 'elements']:
        #TODO(pjm): no commands in synergia yet
        if model_type == 'commands':
            continue
        for m in data['models'][model_type]:
            model_schema = _SCHEMA['model'][_model_name_for_data(m)]
            callback(state, m)

            for k in sorted(m):
                if k not in model_schema:
                    continue
                element_schema = model_schema[k]
                callback(state, m, element_schema, k)


#TODO(pjm): from template.elegant
def _iterator_lattice_elements(state, model, element_schema=None, field_name=None):
    # only interested in elements, not commands
    if '_type' in model:
        return
    if element_schema:
        state['field_index'] += 1
        if field_name in ['name', 'type', '_id'] or re.search('(X|Y|File)$', field_name):
            return
        value = model[field_name]
        default_value = element_schema[2]
        if value is not None and default_value is not None:
            if str(value) != str(default_value):
                if model['type'] == 'SCRIPT' and field_name == 'command':
                    for f in ('commandFile', 'commandInputFile'):
                        if f in model and model[f]:
                            fn = template_common.lib_file_name(model['type'], f, model[f])
                            value = re.sub(r'\b' + re.escape(model[f]) + r'\b', fn, value)
                    if model['commandFile']:
                        value = './' + value
                if element_schema[1] == 'RPNValue':
                    value = _format_rpn_value(value)
                if element_schema[1].startswith('InputFile'):
                    value = template_common.lib_file_name(model['type'], field_name, value)
                    if element_schema[1] == 'InputFileXY':
                        value += '={}+{}'.format(model[field_name + 'X'], model[field_name + 'Y'])
                elif element_schema[1] == 'OutputFile':
                    value = state['filename_map']['{}{}{}'.format(model['_id'], _FILE_ID_SEP, state['field_index'])]
                #TODO(pjm): don't quote numeric constants
                state['lattice'] += '{}={},'.format(field_name, value)
    else:
        state['field_index'] = 0
        if state['lattice']:
            state['lattice'] = state['lattice'][:-1]
            state['lattice'] += ';\n'
        state['lattice'] += '{}: {},'.format(model['name'].upper(), model['type'])
        state['beamline_map'][model['_id']] = model['name']


#TODO(pjm): from template.elegant
def _model_name_for_data(model):
    return 'command_{}'.format(model['_type']) if '_type' in model else model['type']


def _plot_field(field):
    m = re.match('(\w+)emit', field)
    if m:
        return 'emit{}'.format(m.group(1)), m.group(1), None
    m = re.match('(\w+)(mean|std)', field)
    if m:
        return m.group(2), m.group(1), None
    m = re.match('^(\wp?)(\wp?)(corr|mom2)', field)
    if m:
        return m.group(3), m.group(1), m.group(2)
    assert False, field


def _plot_label(field, labels):
    for values in labels:
        if field == values[0]:
            return values[1]
    return field


def _plot_values(h5file, field):
    name, coord1, coord2 = _plot_field(field)
    dimension = len(h5file[name].shape)
    if dimension == 1:
        return h5file[name][:].tolist()
    if dimension == 2:
        return h5file[name][_COORD6.index(coord1), :].tolist()
    if dimension == 3:
        return h5file[name][_COORD6.index(coord1), _COORD6.index(coord2), :].tolist()
    assert False, dimension


def _sort_beamlines_by_length(lines):
    res = []
    for name in lines:
        res.append([name, len(lines[name])])
    return list(reversed(sorted(res, key=lambda v: v[1])))


def _validate_data(data, schema):
    # ensure enums match, convert ints/floats, apply scaling
    enum_info = template_common.validate_models(data, schema)
    for m in data['models']['elements']:
        template_common.validate_model(m, schema['model'][_model_name_for_data(m)], enum_info)
