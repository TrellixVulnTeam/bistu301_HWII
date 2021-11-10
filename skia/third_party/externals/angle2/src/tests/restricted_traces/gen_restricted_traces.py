#!/usr/bin/python3
#
# Copyright 2020 The ANGLE Project Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# gen_restricted_traces.py:
#   Generates integration code for the restricted trace tests.

import getpass
import glob
import fnmatch
import re
import json
import os
import sys

GNI_TEMPLATE = """\
# GENERATED FILE - DO NOT EDIT.
# Generated by {script_name} using data from {data_source_name}
#
# Copyright 2020 The ANGLE Project Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
#
# A list of all restricted trace tests, paired with their context.
# Can be consumed by tests/BUILD.gn.

angle_restricted_traces = [
{test_list}
]
"""

HEADER_TEMPLATE = """\
// GENERATED FILE - DO NOT EDIT.
// Generated by {script_name} using data from {data_source_name}
//
// Copyright 2020 The ANGLE Project Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
//
// {filename}: Types and enumerations for trace tests.

#ifndef ANGLE_RESTRICTED_TRACES_AUTOGEN_H_
#define ANGLE_RESTRICTED_TRACES_AUTOGEN_H_

#include <cstdint>
#include <vector>
#include <KHR/khrplatform.h>
#include <EGL/egl.h>

#include "restricted_traces_export.h"

namespace trace_angle
{{
using GenericProc = void (*)();
using LoadProc    = GenericProc(KHRONOS_APIENTRY *)(const char *);
ANGLE_TRACE_LOADER_EXPORT void LoadEGL(LoadProc loadProc);
ANGLE_TRACE_LOADER_EXPORT void LoadGLES(LoadProc loadProc);

static constexpr size_t kTraceInfoMaxNameLen = 128;

static constexpr uint32_t kDefaultReplayContextClientMajorVersion = 3;
static constexpr uint32_t kDefaultReplayContextClientMinorVersion = 1;
static constexpr uint32_t kDefaultReplayDrawSurfaceColorSpace = EGL_COLORSPACE_LINEAR;

struct TraceInfo
{{
    char name[kTraceInfoMaxNameLen];
    uint32_t contextClientMajorVersion;
    uint32_t contextClientMinorVersion;
    uint32_t frameEnd;
    uint32_t frameStart;
    uint32_t drawSurfaceWidth;
    uint32_t drawSurfaceHeight;
    uint32_t drawSurfaceColorSpace;
    uint32_t displayPlatformType;
    uint32_t displayDeviceType;
    int configRedBits;
    int configBlueBits;
    int configGreenBits;
    int configAlphaBits;
    int configDepthBits;
    int configStencilBits;
    bool isBinaryDataCompressed;
    bool areClientArraysEnabled;
    bool isBindGeneratesResourcesEnabled;
    bool isWebGLCompatibilityEnabled;
    bool isRobustResourceInitEnabled;
}};

ANGLE_TRACE_EXPORT const TraceInfo &GetTraceInfo(const char *traceName);
}}  // namespace trace_angle

#endif  // ANGLE_RESTRICTED_TRACES_AUTOGEN_H_
"""

SOURCE_TEMPLATE = """\
// GENERATED FILE - DO NOT EDIT.
// Generated by {script_name} using data from {data_source_name}
//
// Copyright 2020 The ANGLE Project Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.
//
// {filename}: Types and enumerations for trace tests.

#include "{filename}.h"

#include "common/PackedEnums.h"
#include "common/system_utils.h"

{trace_includes}

namespace trace_angle
{{
namespace
{{
constexpr size_t kNumTraces = {num_traces};
struct TracePair
{{
    const char name[kTraceInfoMaxNameLen];
    TraceInfo info;
}};
constexpr TracePair kTraceInfos[kNumTraces] = {{
{trace_infos}
}};
}}

const TraceInfo &GetTraceInfo(const char *traceName)
{{
    // Could be improved using std::lower_bound.
    for (const TracePair &tracePair : kTraceInfos)
    {{
        if (strncmp(tracePair.name, traceName, kTraceInfoMaxNameLen) == 0)
        {{
            return tracePair.info;
        }}
    }}
    UNREACHABLE();
    return kTraceInfos[0].info;
}}
}}  // namespace trace_angle
"""

CIPD_TRACE_PREFIX = 'angle/traces'
EXPERIMENTAL_CIPD_PREFIX = 'experimental/google.com/%s/angle/traces'
DEPS_PATH = '../../../DEPS'
DEPS_START = '# === ANGLE Restricted Trace Generated Code Start ==='
DEPS_END = '# === ANGLE Restricted Trace Generated Code End ==='
DEPS_TEMPLATE = """\
  'src/tests/restricted_traces/{trace}': {{
      'packages': [
        {{
            'package': '{trace_prefix}/{trace}',
            'version': 'version:{version}',
        }},
      ],
      'dep_type': 'cipd',
      'condition': 'checkout_angle_restricted_traces',
  }},
"""


def reject_duplicate_keys(pairs):
    found_keys = {}
    for key, value in pairs:
        if key in found_keys:
            raise ValueError("duplicate key: %r" % (key,))
        else:
            found_keys[key] = value
    return found_keys


# TODO(http://anglebug.com/5878): Revert back to non-autogen'ed file names for the angledata.gz.
def get_angledata_filename(trace):
    angledata_files = glob.glob('%s/%s*angledata.gz' % (trace, trace))
    assert len(angledata_files) == 1, "Trace '%s' has %d angledata.gz files" % (
        trace, len(angledata_files))
    return angledata_files[0].replace('\\', '/')


# TODO(jmadill): Remove the GNI generation. http://anglebug.com/5133
def gen_gni(traces, gni_file, format_args):
    test_list = []
    for trace in traces:
        context = get_context(trace)
        angledata_file = get_angledata_filename(trace)
        txt_file = '%s/%s_capture_context%s_files.txt' % (trace, trace, context)
        json_file_name = '%s/%s.json' % (trace, trace)
        if os.path.exists(txt_file):
            with open(txt_file) as f:
                files = f.readlines()
                f.close()
                source_files = ['"%s/%s"' % (trace, file.strip()) for file in files]
        else:
            assert os.path.exists(json_file_name), '%s does not exist' % json_file_name
            with open(json_file_name) as f:
                json_data = json.loads(f.read())
                files = json_data["TraceFiles"]

        source_files = ['"%s/%s"' % (trace, file.strip()) for file in files]
        data_files = ['"%s"' % angledata_file]
        if os.path.exists(json_file_name):
            data_files.append('"%s"' % json_file_name)

        for prefix_expr in ['%s/%s_capture_context%s', '%s/%s_context%s']:
            prefix = prefix_expr % (trace, trace, context)
            prefix_cpp = '%s.cpp' % prefix
            if os.path.exists(prefix_cpp):
                break

        assert os.path.exists(prefix_cpp), '%s does not exist' % prefix_cpp

        test_list += [
            '["%s", %s, [%s], [%s], "%s"]' %
            (trace, context, ','.join(source_files), ','.join(data_files), prefix)
        ]

    format_args['test_list'] = ',\n'.join(test_list)
    gni_data = GNI_TEMPLATE.format(**format_args)
    with open(gni_file, "w") as out_file:
        out_file.write(gni_data)
    return True


def contains_string(trace, string):
    """Determines if the trace contains a string"""
    for file in os.listdir(trace):
        if fnmatch.fnmatch(file, '*.h'):
            with open(os.path.join(trace, file)) as f:
                if string in f.read():
                    return True
    return False


def contains_context_version(trace):
    """Determines if the trace contains the major/minor context version"""
    return contains_string(trace, 'kReplayContextClientMajorVersion')


def contains_colorspace(trace):
    """Determines if the trace contains an EGL surface color space"""
    return contains_string(trace, 'kReplayDrawSurfaceColorSpace')


def json_metadata_exists(trace):
    return os.path.isfile('%s/%s.json' % (trace, trace))


def get_trace_info(trace):
    # Skip getting trace info if we're using JSON metadata.
    # TODO: Remove generated code. http://anglebug.com/5133
    if json_metadata_exists(trace):
        return ''

    # Some traces don't contain major/minor version, so use defaults
    info = [f'"{trace}"']
    if contains_context_version(trace):
        info += [
            f'{trace}::kReplayContextClientMajorVersion',
            f'{trace}::kReplayContextClientMinorVersion'
        ]
    else:
        info += [
            'kDefaultReplayContextClientMajorVersion', 'kDefaultReplayContextClientMinorVersion'
        ]

    info += [
        f'{trace}::kReplayFrameStart', f'{trace}::kReplayFrameEnd',
        f'{trace}::kReplayDrawSurfaceWidth', f'{trace}::kReplayDrawSurfaceHeight'
    ]

    if contains_colorspace(trace):
        info += [f'{trace}::kReplayDrawSurfaceColorSpace']
    else:
        info += ['kDefaultReplayDrawSurfaceColorSpace']

    # Add placeholder fields to fix an MSVC warning.
    info += ['0'] * 8
    info += ['false'] * 5

    return ", ".join(info)


def get_context(trace):
    """Returns the trace context number."""
    # TODO(jmadill): Remove the txt scan once migrated. http://anglebug.com/5133
    # Load up the only header present for each trace
    for file in os.listdir(trace):
        if fnmatch.fnmatch(file, '*.txt'):
            # Strip the extension to isolate the context by scanning
            # for numbers leading up to the last one, i.e.:
            #     app_capture_context123_files.txt
            #                          ^^
            #                  start---||---end
            start = len(file) - 11
            end = start + 1
            while file[start - 1].isdigit():
                start -= 1
            context = file[start:end]
            assert context.isnumeric(), 'Trace context number is not numeric: %s' % context
            return context

    expr = re.compile(r'.*_context(\d+).cpp')
    for file in os.listdir(trace):
        m = expr.match(file)
        if m:
            context = m.group(1)
            assert context.isnumeric(), 'Trace context number is not numeric: %s' % context
            return context
    assert False, 'Failed to find context number for %s' % trace


def get_header_name(trace):
    return '%s/%s_capture_context%s.h' % (trace, trace, get_context(trace))


def gen_header(header_file, format_args):
    header_data = HEADER_TEMPLATE.format(**format_args)
    with open(header_file, "w") as out_file:
        out_file.write(header_data)
    return True


def gen_source(source_file, format_args):
    source_data = SOURCE_TEMPLATE.format(**format_args)
    with open(source_file, "w") as out_file:
        out_file.write(source_data)
    return True


def gen_git_ignore(traces):
    ignores = ['%s/' % trace for trace in traces]
    with open('.gitignore', 'w') as out_file:
        out_file.write('\n'.join(sorted(ignores)))
    return True


def read_json(json_file):
    with open(json_file) as map_file:
        return json.loads(map_file.read(), object_pairs_hook=reject_duplicate_keys)


def update_deps(trace_pairs):
    # Generate substitution string
    replacement = ""
    for (trace, version) in trace_pairs:
        if 'x' in version:
            version = version.strip('x')
            trace_prefix = EXPERIMENTAL_CIPD_PREFIX % getpass.getuser()
        else:
            trace_prefix = CIPD_TRACE_PREFIX
        sub = {'trace': trace, 'version': version, 'trace_prefix': trace_prefix}
        replacement += DEPS_TEMPLATE.format(**sub)

    # Update DEPS to download CIPD dependencies
    new_deps = ""
    with open(DEPS_PATH) as f:
        in_deps = False
        for line in f:
            if in_deps:
                if DEPS_END in line:
                    new_deps += replacement
                    new_deps += line
                    in_deps = False
            else:
                if DEPS_START in line:
                    new_deps += line
                    in_deps = True
                else:
                    new_deps += line
        f.close()

    with open(DEPS_PATH, 'w') as f:
        f.write(new_deps)
        f.close()

    return True


def main():
    json_file = 'restricted_traces.json'
    gni_file = 'restricted_traces_autogen.gni'
    header_file = 'restricted_traces_autogen.h'
    source_file = 'restricted_traces_autogen.cpp'

    json_data = read_json(json_file)
    if 'traces' not in json_data:
        print('Trace data missing traces key.')
        return 1
    trace_pairs = [trace.split(' ') for trace in json_data['traces']]
    traces = [trace_pair[0] for trace_pair in trace_pairs]

    # auto_script parameters.
    if len(sys.argv) > 1:
        inputs = [json_file]

        # Note: we do not include DEPS in the list of outputs to simplify the integration.
        # Otherwise we'd continually need to regenerate on any roll.
        outputs = [gni_file, header_file, source_file, '.gitignore']

        if sys.argv[1] == 'inputs':
            print(','.join(inputs))
        elif sys.argv[1] == 'outputs':
            print(','.join(outputs))
        else:
            print('Invalid script parameters.')
            return 1
        return 0

    format_args = {
        'script_name': os.path.basename(__file__),
        'data_source_name': json_file,
    }

    if not gen_gni(traces, gni_file, format_args):
        print('.gni file generation failed.')
        return 1

    trace_infos = ['{"%s", {%s}}' % (trace, get_trace_info(trace)) for trace in traces]

    no_json_traces = filter(lambda trace: not json_metadata_exists(trace), traces)
    includes = ['#include "%s"' % get_header_name(trace) for trace in no_json_traces]

    format_args['filename'] = 'restricted_traces_autogen'
    format_args['num_traces'] = len(trace_infos)
    format_args['trace_includes'] = '\n'.join(includes)
    format_args['trace_infos'] = ',\n'.join(trace_infos)
    if not gen_header(header_file, format_args):
        print('.h file generation failed.')
        return 1

    if not gen_source(source_file, format_args):
        print('.cpp file generation failed.')
        return 1

    if not gen_git_ignore(traces):
        print('.gitignore file generation failed')
        return 1

    if not update_deps(trace_pairs):
        print('DEPS file update failed')
        return 1

    return 0


if __name__ == '__main__':
    sys.exit(main())