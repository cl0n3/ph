from setuptools import setup

setup(
    name='ph',
    version='0.9',
    packages=[''],
    url='https://github.com/cl0n3/ph',
    license='MIT',
    author='Gary Smith',
    author_email='garyjsmith62@gmail.com',
    description='A driver for a light-based PH sensor.',

    install_requires=[
        'pigpio'
    ]
)
