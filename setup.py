
from distutils.core import setup

setup(name='Slobby',
      version='1.0',
      description='Minimalistic web-based user interface for slobs',
      author='Igor Tkach',
      author_email='itkach@gmail.com',
      url='http://github.com/itkach/slobby',
      license='GPL3',
      packages=['slobby'],
      package_data={'slobby': ['slobby.html']},
      install_requires=['Slob >= 1.0', 'CherryPy >= 3.2'])
