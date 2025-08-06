from setuptools import setup, find_packages

setup(
    name="hermes",
    version="0.1",
    package_dir={"": "src"},           # src/ is relative to setup.py location
    packages=find_packages(where="src"), # src/ is relative to setup.py location
    install_requires=[
        # your dependencies here
    ],
) 