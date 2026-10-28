/*---------------------------------------------------------------------------*\
  =========                 |
  \\      /  F ield         | OpenFOAM: The Open Source CFD Toolbox
   \\    /   O peration     |
    \\  /    A nd           | www.openfoam.com
     \\/     M anipulation  |
-------------------------------------------------------------------------------
    Copyright (C) 2019-2021 OpenCFD Ltd.
    Copyright (C) YEAR AUTHOR, AFFILIATION
-------------------------------------------------------------------------------
License
    This file is part of OpenFOAM.

    OpenFOAM is free software: you can redistribute it and/or modify it
    under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    OpenFOAM is distributed in the hope that it will be useful, but WITHOUT
    ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
    FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License
    for more details.

    You should have received a copy of the GNU General Public License
    along with OpenFOAM.  If not, see <http://www.gnu.org/licenses/>.

\*---------------------------------------------------------------------------*/

#include "functionObjectTemplate.H"
#define namespaceFoam  // Suppress <using namespace Foam;>
#include "fvCFD.H"
#include "unitConversion.H"
#include "addToRunTimeSelectionTable.H"

// * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * //

namespace Foam
{

// * * * * * * * * * * * * * * Static Data Members * * * * * * * * * * * * * //

defineTypeNameAndDebug(CpFieldFunctionObject, 0);

addRemovableToRunTimeSelectionTable
(
    functionObject,
    CpFieldFunctionObject,
    dictionary
);


// * * * * * * * * * * * * * * * Global Functions  * * * * * * * * * * * * * //

// dynamicCode:
// SHA1 = 16957f924f4ce33b0da077f1841e9d6dd19bd893
//
// unique function name that can be checked if the correct library version
// has been loaded
extern "C" void CpField_16957f924f4ce33b0da077f1841e9d6dd19bd893(bool load)
{
    if (load)
    {
        // Code that can be explicitly executed after loading
    }
    else
    {
        // Code that can be explicitly executed before unloading
    }
}


// * * * * * * * * * * * * * * * Local Functions * * * * * * * * * * * * * * //

//{{{ begin localCode

//}}} end localCode

} // End namespace Foam


// * * * * * * * * * * * * * Private Member Functions  * * * * * * * * * * * //

const Foam::fvMesh&
Foam::CpFieldFunctionObject::mesh() const
{
    return refCast<const fvMesh>(obr_);
}


// * * * * * * * * * * * * * * * * Constructors  * * * * * * * * * * * * * * //

Foam::
CpFieldFunctionObject::
CpFieldFunctionObject
(
    const word& name,
    const Time& runTime,
    const dictionary& dict
)
:
    functionObjects::regionFunctionObject(name, runTime, dict)
{
    read(dict);
}


// * * * * * * * * * * * * * * * * Destructor  * * * * * * * * * * * * * * * //

Foam::
CpFieldFunctionObject::
~CpFieldFunctionObject()
{}


// * * * * * * * * * * * * * * * Member Functions  * * * * * * * * * * * * * //

bool
Foam::
CpFieldFunctionObject::read(const dictionary& dict)
{
    if (false)
    {
        printMessage("read CpField");
    }

//{{{ begin code
    
//}}} end code

    return true;
}


bool
Foam::
CpFieldFunctionObject::execute()
{
    if (false)
    {
        printMessage("execute CpField");
    }

//{{{ begin code
    #line 117 "/Users/moosecoding/school/gatech/Freshman/supersonic/Cobra/CFD/openfoam/plane_cfd/run_cobra_lvl4_aoa8_v20/system/controlDict/functions/codedCp"
auto* CpPtr = mesh().getObjectPtr<volScalarField>("Cp");
            if (!CpPtr)
            {
                CpPtr = new volScalarField
                (
                    IOobject
                    (
                        "Cp",
                        mesh().time().timeName(),
                        mesh(),
                        IOobject::NO_READ,
                        IOobject::AUTO_WRITE,
                        IOobject::REGISTER
                    ),
                    mesh(),
                    dimensionedScalar(dimless, Zero)
                );
                regIOobject::store(CpPtr);
            }
            const auto& p = mesh().lookupObject<volScalarField>("p");
            const dimensionedScalar q("q", p.dimensions(), 200);
            *CpPtr = p/q;
//}}} end code

    return true;
}


bool
Foam::
CpFieldFunctionObject::write()
{
    if (false)
    {
        printMessage("write CpField");
    }

//{{{ begin code
    
//}}} end code

    return true;
}


bool
Foam::
CpFieldFunctionObject::end()
{
    if (false)
    {
        printMessage("end CpField");
    }

//{{{ begin code
    
//}}} end code

    return true;
}


// ************************************************************************* //

