#!/usr/bin/env python

from time import sleep

from simtk.openmm.app import PDBFile, AmberPrmtopFile, AmberInpcrdFile, NoCutoff, CutoffNonPeriodic
from simtk import openmm

from mdtraj import Topology

__all__ = ["OmmSystem"]


class OmmSystem(object):
    """OmmSystem is a wrapper around the OpenMM System object
    that does a bunch of simple stuff for us with simpler API

    Initialize from Forcefield-specific input or a previously
    saved OpenMM 'system.xml'-type file. In either case, some
    input must be given to initialze the parameters and coords
    for the system. 

    Currently implemented initialize formats
      - Amber
    TODO
      - Gromacs
      - Charmm
      - strings giving OpenMM-packaged ff xmls
    TODO move useful bits of John's setupsystem functionality
    TODO move useful bits of John's runopenmm functionality

    Attributes
    ----------
    system   :: OpenMM `System` instance
    topology :: MTraj `Topology` instance
    restraints :: `dict` of restraint forces

    Methods
    -------
    apply_restraint_force ::
        take a configured restraint force and add it
        to the `system`

    initialize_restraint_force ::
        specify a restraint definition to load for the
        system. after initializing, interactions can
        be added restraint using this force with the
        method `add_restraint_interactions`

    add_restraint_interactions ::
        give list of interactions each, used to create
        a restraint instance, specifying the atom group
        and the restraint parameters to apply to the
        group

    save_pdb :: probably doesn't work at the moment
    save_xml :: save `system` with `XmlSerializer`
    load_xml :: load `system` with `XmlSerializer`
    """

    @property
    def initial_positions(self):
        """Retrieve the initial positions from the system
        initializer objects
        """
        if hasattr(self._positions, "positions"):
            return self._positions.positions
        else:
            return list()

    @property
    def restraints(self):
        """dict with the API calls, atom groups and force
        parameters needed to generate all the given restraints
        """
        return self._restraints


    def __init__(self, ff_type=None, system_file=None, **kwargs):
        """Two pathways can be used starting from FF-specific files
        or OpenMM XML system. Additional kwargs are variously used
        depending on the forcefield / pathway that was chosen.

        supported ff_type
        -----------------
        amber :: give a prmtop and an inpcrd
        openmm :: give an XML file for the system

        supported kwargs
        ----------------
        topology :: system-specific or not depending on FF
        coordinates :: source of coordinates for initial state
        """

        assert (ff_type is None) or (system_file is None)

        # This dict will store the API calls
        # along with atom groups and force
        # parameters needed to generate all
        # the given restraints
        self._restraints = dict()
        self._topology   = None

        topofile  = kwargs.get("topology", None)
        coordfile = kwargs.get("coordinates", None)

        if ff_type is not None:
            if ff_type.lower() == "amber":
                prmtop = AmberPrmtopFile(topofile)
                inpcrd = AmberInpcrdFile(coordfile)
                self.system = prmtop.createSystem(nonbondedMethod=NoCutoff) #CutoffNonPeriodic - according to Ada, this would be good bc its what amber does - preliminary tests show that this hurts small/medium proteins
                self._topology = Topology.from_openmm(prmtop.topology)
                self._positions = inpcrd

        elif system_file is not None:
            self.load_xml(system_file)
            if topofile:
                if topofile.endswith(".pdb"):
                    # this line is a bit silly but Topology class
                    # doesn't seem to directly load PDB so keeps
                    # the imports clean
                    self._topology = Topology.from_openmm(
                        PDBFile(topofile).topology)

        else:
            # Inspect and set ff_type
            # TODO ff_type as instance attribute
            pass


    @property
    def topology(self):
        if not self._topology:
            return None

        elif hasattr(self._topology, "topology"):
            return self._topology.topology

        else:
            return self._topology


    def initialize_restraint_force(self, restraint_definition, interactions=list()):

        assert len(restraint_definition) == 1
        assert isinstance(restraint_definition, dict)

        # PROGRAMMATIC use of the dict fields happens here
        restraint_type    = list(restraint_definition)[0]
        rd                = restraint_definition[restraint_type]
        restraint_formula = rd.get("formula", list())
        restraint_pars    = rd.get("parameters", list())

        # Each interaction makes a restraint instance
        # by calling instance_method w/ atom group
        # the physical parameters
        instance_call     = rd.get("restraint", dict())
        instance_units    = rd.get("units", dict())
        instance_method   = list(instance_call)[0]

        assert len(instance_call) == 1
        assert isinstance(instance_call[instance_method][0], int)

        assert instance_call[instance_method][1] == len(instance_units)
        instance_call[instance_method][1] = instance_units

        restraint_force   = getattr(openmm, restraint_type)(*restraint_formula)
    
        for mpar in restraint_pars:
            assert len(mpar) == 1
            method,parameter = next(iter(mpar.items()))
            getattr(restraint_force, method)(*parameter)

        self._restraints.update(
            {restraint_type : [restraint_force, instance_call]}
        )

        if interactions:
            self.add_restraint_interactions(restraint_type, interactions)


    def _aidx_from_resatom(self, resatom):

        assert self.topology  # if None, can't get atom index from resatom

        # MDTraj residues start numbering at 1
        mdtrajatom = self.topology.select("residue %d and name %s" % (
            resatom[0], resatom[1].upper()
        ))
        if mdtrajatom:
            return int(mdtrajatom)
        else:
            return -1

    def _format_interactions(self, restraint_type, interactions):

        method       = list(self._restraints[restraint_type][1])[0]
        method_pars  = self._restraints[restraint_type][1][method]
        n_atoms      = method_pars[0]
        par_units    = method_pars[1]

        for interaction in interactions:
            atom_indices = [
                self._aidx_from_resatom(ra)
                for ra in interaction[:n_atoms]
            ]
            if all([ai > 0 for ai in atom_indices]):
                parameters   = [
                    par*par_units[i]
                    for i,par in enumerate(interaction[n_atoms:])
                ]

                yield atom_indices, parameters


    # Consider taking atom_group+parameters separately?
    def add_restraint_interactions(self, restraint_type, interactions):

        assert restraint_type in self._restraints
        assert isinstance(interactions, (list, tuple))

        restraint_force, restraint_method = self._restraints[restraint_type]
        interaction_method = list(restraint_method)[0]

        for atom_group, parameters in self._format_interactions(
            restraint_type, interactions
        ):

            assert isinstance(atom_group, list)

            rargs = atom_group
            rargs.append(parameters)

            getattr(restraint_force, interaction_method)(*rargs)


    def apply_restraint_force(self, restraint_type):
        self.system.addForce(
            self._restraints[restraint_type][0]
        )

    # Get a given force 
    def get_force(self, type_name):
        forces = self.system.getForces()
        num_forces = self.system.getNumForces()
        for i in range(num_forces):
            #print("force name: " + str(forces[i].__class__.__name__) + "\n")
            if forces[i].__class__.__name__==type_name:
               return forces[i]

    # Get a given force's index 
    def get_force_id(self, type_name):
        forces = self.system.getForces()
        num_forces = self.system.getNumForces()
        for i in range(num_forces):
            #print("force name: " + str(forces[i].__class__.__name__) + "\n")
            if forces[i].__class__.__name__==type_name:
               return i

    # Remove the nonbonded forces
    def remove_nonbonded_forces(self):
        i = self.get_force_id('NonbondedForce')
        self.nonbonded_force = self.system.getForce(i)
        self.system.removeForce(i) 
         
    # Remove the repulsive force
    def remove_repulsive_force(self):
        i = self.get_force_id('CustomNonbondedForce')
        self.nonbonded_force = self.system.getForce(i)
        self.system.removeForce(i)    

    # Apply non-bonded forces
    def apply_nonbonded_forces(self):
        i = self.system.addForce(self.nonbonded_force)
        print("Nonbonded forces are added back into the system with the index " + str(i) +"\n")

    # Add repulsive force
    def apply_repulsive_force(self, weight):
        #energy_exp = '4*epsilon*((sigma/r)^12-(sigma/r)^6); sigma=0.5*(sigma1+sigma2); epsilon=sqrt(epsilon1*epsilon2)'
        #energy_exp = '4*w_a*epsilon*((sigma/r)^12); sigma=0.5*(sigma1+sigma2); epsilon=sqrt(epsilon1*epsilon2)'
        #energy_exp = '4*w_a*((sigma/r)^12); sigma=0.5*(sigma1+sigma2)'
        #energy_exp = 'w_a*((0.8*1.122*sigma)^2-r^2)^2; sigma=0.5*(sigma1+sigma2)'
        energy_exp = 'w_a*((0.8*sigma*(2)^(1/6))^2-r^2)^2; sigma=0.5*(sigma1+sigma2)'
        repulsive_force = openmm.CustomNonbondedForce(energy_exp)
        #repulsive_force.setNonbondedMethod(self.nonbonded_force.getNonbondedMethod()) 
        repulsive_force.setNonbondedMethod(openmm.CustomNonbondedForce.CutoffPeriodic)
        repulsive_force.addPerParticleParameter('sigma')
        #repulsive_force.addPerParticleParameter('epsilon')
        repulsive_force.setCutoffDistance(self.nonbonded_force.getCutoffDistance())
        #print("repulsive force: " + str(repulsive_force)+ "\n")
        #print("num of parameters: " + str(repulsive_force.getNumPerParticleParameters())+ "\n")
        #print("Parameters:  " + str(repulsive_force.getParticelParameters(0))+ "\n")
        #print("repulsive force; " + str(repulsive_force.getPerParticleParameterName(0))+ "\n")
        #self.system.addForce(repulsive_force)
    
        num_particles = self.nonbonded_force.getNumParticles();
        #avg_sigma = 0.0
        #avg_epsilon = 0.0
        sigmas = {} 
        #epsilons = {}
        for i in range(num_particles):
           charge, sigma, epsilon = self.nonbonded_force.getParticleParameters(i)
           sigmas[i] = sigma
           #epsilons[i] = epsilon
           #print("sigma: " + str(sigma._value) + "epsilon: " + str(epsilon)+"\n") 
        #avg_sigma = sum(sigmas)/num_particles
          # avg_epsilon += epsilon._value
        
        #avg_epsilon /= num_particles

        for i in range(num_particles):
           repulsive_force.addParticle([sigmas[i]])
           #repulsive_force.addParticle([avg_sigma])

        repulsive_force.addGlobalParameter('w_a', weight)
       # print('num sys part: ' +str(self.system.getNumParticles())+ '\n')
       # print('num CNBF part: ' +str( repulsive_force.getNumParticles())+ '\n')
        self.system.addForce(repulsive_force)

    def save_pdb(self, pdb_file):
        PDBFile.write(pdb_file, self.topology)


    def save_xml(self, system_file):
        with open(system_file, "w") as f:
            f.write(openmm.XmlSerializer.serialize(self.system))


    def load_xml(self, system_file):
        attempt = 0
        retries = 20
        while True:
            try:
                with open(system_file) as f:
                    self.system = openmm.XmlSerializer.deserialize(f.read())
                return
    
            except ValueError as e:
                if attempt < retries:
                    attempt += 1
                    sleep(5*random.random())
                else:
                    raise e

