import numpy as np
import lmfit as lm

from scipy.ndimage.measurements import center_of_mass as CoM

from obstools.psf.psf import GaussianPSF as _GaussianPSF
                             

#****************************************************************************************************
class GaussianPSF(_GaussianPSF):
    _pnames_ordered = 'x0, y0, z0, a, b, c, d'.split(', ')
    params = lm.Parameters()
    
    #limiting parameters seems to thwart uncertainty estimates of the parameters... so we HACK!
    _ix_not_neg = list(range(7))        #_GaussianPSF.Npar
    _ix_not_neg.pop(_pnames_ordered.index('b'))       #parameter b is allowed to be negative
    
    for pn in _pnames_ordered:
        params.add(pn, value=1)
    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def __call__(self, params, grid):
        p = self.convert_params(params)
        return _GaussianPSF.__call__(self, p, *grid[::-1])
    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def residuals(self, p, data, grid):
        '''Difference between data and model'''
        return data - self(p, grid)
    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def rs(self, p, data, grid):
        return np.square(self.residuals(p, data, grid))
    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def rss(self, p, data, grid):
        return self.rs(p, data, grid).sum()
    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def wrs(self, params, data, grid, data_stddev=None):
        #pvd = params.valuesdict()
        #p = [pvd[pn] for pn in self._pnames_ordered]
        if data_stddev is None:
            return self.rs(params, data, grid)
        return self.rs(params, data, grid) / data_stddev
    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def fwrs(self, params, data, grid, data_stdev=None):
        return self.wrs(params, data, grid, data_stdev).flatten()
    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def coeff(self, covariance_matrix):
        '''
        Return a, b, c coefficents for the form:
        z0*np.exp(-(a*(x-x0)**2 -2*b*(x-x0)*(y-y0) + c*(y-y0)**2 )) + d
        '''
        sigx2, sigy2 = np.diagonal(covariance_matrix)
        cov = covariance_matrix[0,1]
        cor2 = cov**2 / (sigx2*sigy2)
        
        f = 0.5 / (1 - cor2)
        a = f / sigx2
        b = f * (cor2/cov)
        c = f / sigy2
        
        return a, b, c
    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def correlation(self, params):
        '''Pearsons correlation coefficient '''
        #covm = self.covariance_matrix(params)
        (sigx2, covar), (_, sigy2) = self.covariance_matrix(params)
        return covar / np.sqrt(sigx2*sigy2)

    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def covariance_matrix(self, params):
        _, _, _, a, b, c, _ = self.convert_params(params)
        #rho = self.correlation(params)
        #P = np.array([[a,   -b],
        #              [-b,  c ]]) * 2
        detP = (a*c + b*b) * 4
        #inverse of precision matrix
        return (1 / detP) * np.array([[c,   b],
                                      [b,   a]]) * 2
        #return np.linalg.inv(P)                              
    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def theta(self, params):
        _, _, _, a, b, c, _ = self.convert_params(params)
        return -0.5*np.arctan2( -2*b, a-c )
        
    
        #fwhm = self.get_fwhm(p)
        #counts = self.integrate(p)
        #sigx, sigy = 1/(2*a), 1/(2*c)           #FIXME #standard deviation along the semimajor and semiminor axes
        #ratio = min(a,c)/max(a,c)               #Ratio of minor to major axis of Gaussian kernel
        #theta = 0.5*np.arctan2( -b, a-c )       #rotation angle of the major axis in sky plane
        #ellipticity = np.sqrt(1-ratio**2)
        #coo = x+offset[0], y+offset[1]
    
    def fwhm(self, params):
        return self.get_fwhm(self.convert_params(params))
    
    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def param_hint(self, data):
        '''Return a guess of the fitting parameters based on the data'''
        
        #location
        #y0, x0 = np.c_[np.where(data==data.max())][0]              #center_of_mass( data ) #NOTE: in case of multiple maxima it only returns the first
        
        bg = np.median(data)
        z0 = data.max() - bg    #use core area only????
        y0, x0 = CoM(data)

        p = np.empty(self.Npar)
        p[self.no_cache] = x0, y0, z0, bg
        #cached parameters will be set by StarFit
        return p
    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def convert_params(self, params):
        '''from lm.Parameters to list of float values'''
        if isinstance(params, lm.Parameters):
            pv = params.valuesdict()
            params = [pv[pn] for pn in self._pnames_ordered]
        return np.array(params)
    
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def _set_param_bounds(self, par0, data):
         #HACK-ish! better to explore full posterior
        '''set parameter bounds based on data'''
        x0, y0, z0, a, b, c, d = self.convert_params(par0)
        #x0, y0 bounds
        #Let x, y only vary across half of window frame
        #sh = np.array(data.shape)
        #(xbl, xbu), (ybl, ybu) = (x0, y0) + (sh/2)[None].T * [1, -1]  
        #par0['x0'].set(min=xbl, max=xbu)
        #par0['y0'].set(min=ybl, max=ybu)
        
        #z0 - (0 to 3 times frame max value)
        #zbl, zbu = (0, z0*3)    #NOTE: hope your initial guess is robust
        #par0['z0'].set(min=zbl, max=zbu)
        
        ##d - sky background
        #dbl, dbu = (0, d*5)
        #par0['d'].set(min=dbl, max=dbu)
        
        for pn in self._pnames_ordered:
            par0[pn].set(min=0)
        
        #NOTE: not sure how to constrain a,b,c params...
        return par0
   
    #~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    def validate(self, p, window):
        p = self.convert_params(p)
        nans = np.isnan(p).any()
        negpars = any(p[self._ix_not_neg] < 0)
        badcoo = any(abs(p[:2] - window/2) >= window/2)
        
        return ~(badcoo | negpars | nans)
        
   
#****************************************************************************************************
class ConstantBG():
    
    params = lm.Parameters()
    params.add('bg', min=0)
    
    def rs(self, p, data):
        return np.square(data - p['bg'].value)

    def wrs(self, p, data, stddev):
        if stddev is None:
            return self.rs(p, data)
        return self.rs(p, data) / stddev
    
    def fwrs(self, p, data, stddev):
        return self.wrs(p, data, stddev)



