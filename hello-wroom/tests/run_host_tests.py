"""Build the firmware-pinned Codec2 and run every WROOM host test, without skips."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest

TESTS = Path(__file__).resolve().parent
COMPONENT = TESTS.parent / 'components' / 'codec2' / 'CMakeLists.txt'
REQUIRED = {
    'test_voice_playback.VoicePlaybackTests.test_worker',
    'test_voice_decoder.DecoderTests.test_decoder',
    'test_voice_playback.VoiceInitializationFailureTests.'
    'test_dma_or_decoder_failure_is_suppressed_until_new_ptt_generation',
}


def prepare(build_dir):
    # Read the firmware declaration, not an independently maintained test pin.
    declaration = COMPONENT.read_text()
    repo = re.search(r'GIT_REPOSITORY\s+(\S+)', declaration).group(1)
    revision = re.search(r'GIT_TAG\s+([0-9a-f]{40})\s', declaration).group(1)
    build_dir.mkdir(parents=True, exist_ok=True)
    source = build_dir / 'source'
    # A fresh checkout avoids stale objects, local edits and mismatched headers.
    if source.exists():
        raise RuntimeError(f'{source} already exists; use a fresh build directory')
    subprocess.run(['git', 'init', str(source)], check=True)
    subprocess.run(['git', '-C', str(source), 'fetch', '--depth=1', repo, revision], check=True)
    subprocess.run(['git', '-C', str(source), 'checkout', '--detach', 'FETCH_HEAD'], check=True)
    actual = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != revision:
        raise RuntimeError(f'Codec2 revision mismatch: {actual} != {revision}')
    library = build_dir / 'libcodec2.so'
    sources = sorted((source / 'src').glob('*.c'))
    if not sources:
        raise RuntimeError('No Codec2 C sources found')
    # Match the firmware component source glob, enabled modes and float constants.
    subprocess.run(['cc', '-std=gnu11', '-O2', '-fPIC', '-shared',
                    '-fsingle-precision-constant', '-DCODEC2_MODE_EN_DEFAULT=0',
                    '-DCODEC2_MODE_2400_EN=1', '-I', str(source / 'src'),
                    *map(str, sources), '-lm', '-o', str(library)], check=True)
    os.environ['ECL_TEST_CODEC2_SRC'] = str(source / 'src')
    os.environ['ECL_TEST_CODEC2_LIB'] = str(library)
    os.environ['ECL_REQUIRE_CODEC2'] = '1'
    print(f'Codec2 revision: {actual}\nCodec2 library: {library}', flush=True)


def test_ids(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from test_ids(test)
        else:
            yield test.id()


def run_tests():
    suite = unittest.defaultTestLoader.discover(str(TESTS))
    missing = REQUIRED - set(test_ids(suite))
    if missing:
        raise RuntimeError(f'Required tests not discovered: {sorted(missing)}')
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped:
        print(f'ERROR: WROOM host tests must not skip: {result.skipped}', file=sys.stderr)
    return 0 if result.wasSuccessful() and not result.skipped else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir', type=Path, required=True,
                        help='Fresh temporary directory for pinned source and host library')
    args = parser.parse_args()
    prepare(args.build_dir.resolve())
    sys.exit(run_tests())
