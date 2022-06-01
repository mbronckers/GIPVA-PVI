import lab as B

class GIBNN:
    def __init__(self, nonlinearity):
        self.nonlinearity = nonlinearity
        self._cache = {}
        
    def sample_posterior(self, key: B.RandomState, ps: dict, ts: dict, zs: dict, S: B.Int=1):
        """
        :param ps: priors. dict<k=layer_name, v=_p>
        :param ts: pseudo-likelihoods. dict<k='layer x', v=dict<k='client x', v=t>>
        :param zs: client-local inducing intputs. dict<k=client_name, v=inducing inputs>
        :param S: number of samples to draw (and thus propagate)

        M inducing points, 
        D input space dimensionality
        """
        _zs = {} # dict to store propagated inducing inputs

        for client_name, client_z in zs.items():
            assert len(client_z.shape) == 2
            
            # z is [M, D]. Change to [S, M, D]]
            _zs[client_name] = B.tile(client_z, S, 1, 1) # only tile intermediate results

        for i, (layer_name, p) in enumerate(ps.items()):

            # Init posterior to prior
            q = p 
            
            # Compute new posterior distribution by multiplying client factors
            for t in ts[layer_name].values():
                q *= t(_zs[client_name])    # propagate prev layer's inducing outputs
            
            # Sample weights from posterior distribution q. q already has S passed via _zs
            key, w = q.sample(key) # w is [S, Dout, Din] of layer i.
            
            # Get rid of last dimension.
            w = w[..., 0] # [S, Dout, Din]
    
            # Compute KL div
            kl_qp = q.kl(p)  # [S, Dlatent] = [S, Dout]
            
            # Sum across output dimensions. [S]
            kl_qp = B.sum(kl_qp, -1) 

            # Save posterior w samples and KL to cache
            self._cache[layer_name] = {"w": w, "kl": kl_qp}

            # Propagate client-local inducing inputs <z> and store prev layer outputs in _zs
            inducing_inputs = _zs
            for client_name, client_z in inducing_inputs.items():
                client_z = B.mm(client_z, w, tr_b=True)         # update z
                
                if i < len(ps.keys()) - 1:                      # non-final layer
                    client_z = self.nonlinearity(client_z)      # forward and updating the inducing inputs
                
                # Always store in _zs
                _zs[client_name] = client_z 
                
        return key, self._cache
                
    def propagate(self, x):
        """Propagates input through BNN using S cached posterior weight samples. 

        :param x: input data

        Returns: output values from propagating x through BNN
        """
        if self._cache is None:
            return None

        if len(x.shape) == 2:
            x = B.tile(x, self.S, 1, 1)

        for i, (layer_name, layer_dict) in enumerate(self._cache.items()):
            x = B.mm(x, layer_dict["w"], tr_b=True)
            if i < len(self._cache.keys()) - 1: # non-final layer
                x = self.nonlinearity(x)
                
        return x
    
    def __call__(self, x):
        return self.propagate(x)

    @property
    def S(self):
        """ Returns cached number of weight samples """
        return self._cache['layer0']['w'].shape[0]

    @property
    def cache(self):
        return self._cache

    @cache.setter
    def cache(self, cache):
        self._cache = cache