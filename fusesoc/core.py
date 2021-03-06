import importlib
import logging
import os
import shutil
import subprocess

from fusesoc import section
from fusesoc import utils
from fusesoc.config import Config
from fusesoc.fusesocconfigparser import FusesocConfigParser
from fusesoc.plusargs import Plusargs
from fusesoc.system import System

logger = logging.getLogger(__name__)


class OptionSectionMissing(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)

class Core:
    def __init__(self, core_file=None, name=None, core_root=None):
        if core_file:
            basename = os.path.basename(core_file)
        self.depend = []
        self.simulators = []

        self.plusargs = None
        self.provider = None
        self.system   = None

        for s in section.SECTION_MAP:
            assert(not hasattr(self, s))
            if(section.SECTION_MAP[s].named):
                setattr(self, s, {})
            else:
                setattr(self, s, None)

        self.core_root = os.path.dirname(core_file)
        self.files_root = self.core_root

        if core_file:

            self.name = basename.split('.core')[0]
            config = FusesocConfigParser(core_file)

            #FIXME : Make simulators part of the core object
            self.simulator        = config.get_section('simulator')

            for s in section.load_all(config, name=self.name):
                if type(s) == tuple:
                    _l = getattr(self, s[0].TAG)
                    _l[s[1]] = s[0]
                    setattr(self, s[0].TAG, _l)
                else:
                    setattr(self, s.TAG, s)
            self.depend     = self.main.depend
            self.simulators = self.main.simulators

            cache_root = os.path.join(Config().cache_root, self.name)
            if config.has_section('plusargs'):
                self.plusargs = Plusargs(dict(config.items('plusargs')))
            if config.has_section('provider'):
                items    = dict(config.items('provider'))

                provider_name = items.get('name')
                if provider_name is None:
                    raise RuntimeError('Missing "name" in section [provider]')
                try:
                    provider_module = importlib.import_module(
                            'fusesoc.provider.%s' % provider_name)
                    self.provider = provider_module.PROVIDER_CLASS(self.name,
                        items, self.core_root, cache_root)
                except ImportError:
                    raise
            if self.provider:
                self.files_root = self.provider.files_root

            system_file = os.path.join(self.core_root, self.name+'.system')
            if os.path.exists(system_file):
                self.system = System(system_file)
        else:
            self.name = name
            self.provider = None


    def cache_status(self):
        if self.provider:
            return self.provider.status()
        else:
            return 'local'

    def setup(self):
        if self.provider:
            if self.provider.fetch():
                self.patch(self.files_root)

    def export(self, dst_dir):
        if os.path.exists(dst_dir):
            shutil.rmtree(dst_dir)

        #FIXME: Separate tb_files to an own directory tree (src/tb/core_name ?)
        src_files = []

        for s in section.SECTION_MAP:
            obj = getattr(self, s)
            if obj:
                if not (type(obj) == dict):
                    src_files += obj.export()

        dirs = list(set(map(os.path.dirname,src_files)))
        for d in dirs:
            if not os.path.exists(os.path.join(dst_dir, d)):
                os.makedirs(os.path.join(dst_dir, d))

        for f in src_files:
            if not os.path.isabs(f):
                if(os.path.exists(os.path.join(self.core_root, f))):
                    shutil.copyfile(os.path.join(self.core_root, f),
                                    os.path.join(dst_dir, f))
                elif (os.path.exists(os.path.join(self.files_root, f))):
                    shutil.copyfile(os.path.join(self.files_root, f),
                                    os.path.join(dst_dir, f))
                else:
                    raise RuntimeError('Cannot find %s in :\n\t%s\n\t%s'
                                  % (f, self.files_root, self.core_root))

    def patch(self, dst_dir):
        #FIXME: Use native python patch instead
        patch_root = os.path.join(self.core_root, 'patches')
        patches = self.main.patches
        if os.path.exists(patch_root):
            for p in sorted(os.listdir(patch_root)):
                patches.append(os.path.join('patches', p))

        for f in patches:
            patch_file = os.path.abspath(os.path.join(self.core_root, f))
            if os.path.isfile(patch_file):
                logger.debug("  applying patch file: " + patch_file + "\n" +
                             "                   to: " + os.path.join(dst_dir))
                try:
                    subprocess.call(['patch','-p1', '-s',
                                     '-d', os.path.join(dst_dir),
                                     '-i', patch_file])
                except OSError:
                    print("Error: Failed to call external command 'patch'")
                    return False
        return True

    def info(self):

        show_list = lambda l: "\n                        ".join(l)
        show_dict = lambda d: show_list(["%s: %s" % (k, d[k]) for k in d.keys()])

        print("CORE INFO")
        print("Name:                   " + self.name)
        print("Core root:              " + self.core_root)
        if self.simulators:
            print("Supported simulators:   " + show_list(self.simulators))
        if self.plusargs: 
            print("\nPlusargs:               " + show_dict(self.plusargs.items))
        if self.depend:
            print("\nCommon dependencies:    " + show_list(self.depend))
        for s in section.SECTION_MAP:
            if s == 'main':
                continue
            obj = getattr(self, s)
            if obj:
                print("== " + s + " ==")
                if(type(obj) == dict):
                    for k, v in obj.items():
                        print(str(k))
                        print(str(v))
                else:
                    print(obj)
